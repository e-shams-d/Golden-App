# M3 Implementation Plan — Authentication, RBAC, Ownership, and Sensitive-Action Assurance

Status: Working implementation plan for hand-off to implementers. Not an approved M0 artifact.
Milestone authority: `Implementation Docs/00_Start_Here/15_Agent_Implementation_Plan.md:598-666`.
Precondition: M2 as merged — identity, RBAC, session and security schema exist
(`alembic/versions/20260801_0007_identity_and_rbac_schema.py`, `_0008_seed_rbac_catalogue.py`,
`_0009_sessions_and_security_events.py`), the Unit of Work commits business state with audit,
outbox and idempotency in one transaction, and ADR-001 is Approved.
Date of this revision: 2026-08-08.

Every claim traceable to a document is cited as `path:line`. Where this plan resolves a divergence
between authorities, the divergence is named and the resolution is recorded in section 2 so it is
raised in the pull request rather than decided silently inside a migration.

---

# 1. What M3 delivers, and the Definition of Done

## 1.1 Scope, as the milestone authority states it

`15_Agent_Implementation_Plan.md:602` sets the goal: "Create separate, revocable security domains
for Trader PWA and Admin Web."

`:604-619` lists thirteen required capabilities: admin and trader login/logout/current-session;
trader registration and pending-approval access; password hashing and reset/admin recovery; session
revocation; account suspension and lock behaviour; backend permission guards; trader ownership
guards; role-aware navigation; CSRF controls for cookie authentication; a recent-auth abstraction; a
separation-of-duty policy service; security-event logging; and rate limiting for authentication.

`:621-633` fixes the role baseline and forbids a permanently omnipotent `super_admin`. `:635-651`
requires permissions to map to explicit actions. `:653-662` lists eight security tests.

## 1.2 Definition of Done (verbatim)

`15_Agent_Implementation_Plan.md:666`:

> M3 is complete when ownership and permission negative tests exist for every implemented protected
> resource and the two frontends cannot access each other's protected surfaces.

This DoD is unlike M2's, and the difference drives the slice order. M2's DoD named **one artifact**
(a sample command) and slice 1 produced it. M3's DoD names **a property of the test suite**: for
every protected resource that exists, a negative ownership test and a negative permission test must
exist. A property of that shape cannot be discharged by writing tests and asserting diligence — the
same "I wrote them all down" claim that drifted four times inside M2 slice 10. It has to be a
machine gate that enumerates protected resources from the router and fails on any that lacks both
negative tests. That gate is slice 10, and every earlier slice is written to feed it.

The second half — "the two frontends cannot access each other's protected surfaces" — is the reason
audience separation is structural in this plan rather than a server-side string comparison
(section 2.3).

`docs/governance/TRACEABILITY_MATRIX.md:25` restates the gate and adds the parts the DoD sentence
omits: "Admin/trader sessions are not interchangeable; logout/revocation works; pending/suspended
actors are denied; backend RBAC and ownership negative tests cover every protected identity
resource; recent-auth uses the approved actor/session/action/resource-bound context while
factor/timeout remain unresolved under ADR-009; technical admin has no financial authority."

The same row records M3's admissible status: "Provisional — production auth and strong-auth choices
remain open."

---

# 2. Authority, precedence, and the decisions this plan makes

## 2.1 Precedence order

`15_Agent_Implementation_Plan.md` §2.2 fixes the order: approved decision/ADR → security and
financial invariants → domain/workflow rules → database integrity → API contract →
architecture/implementation guides → UI/UX → future-phase guidance. It forbids silently choosing an
interpretation and requires the conflict to be recorded in the task and pull request.

Baselines that bind M3 directly:

| Baseline | What it settles for M3 |
|---|---|
| **ADR-001, Approved 2026-08-08** (`docs/adr/ADR_INDEX.md`) | Server-side session records carried by a secure, HTTP-only, `SameSite` cookie, with CSRF protection on every unsafe method. Cookie scope/origins/TLS remain OPS-003; idle and absolute timeouts remain ADR-SEC-002. |
| `docs/governance/permission_catalog.yaml` (approved 2026-08-01) | Canonical permission identifiers. `auth.session.read_own/revoke_own/read_all/revoke_all`, `user.read/create/update/deactivate`, `role.read/manage`, `permission.read`, `break_glass.activate/review` (`:256-296`); `trader.read/create/approve/reject/suspend/reactivate/update_business` (`:306-328`). Doc 05's `admin_user.read`/`admin_user.manage` are recorded aliases mapping to canonical targets (`:758-763`). |
| `docs/governance/FINANCIAL_INTEGRITY_BASELINE.md` §3 | `recent_auth_contexts` bound to actor, active session, action/purpose and resource, with assurance, expiry, revocation and consumption recorded in the command transaction. Resolves DOC-CONFLICT-019. Factor and duration remain ADR-009. |
| `FINANCIAL_INTEGRITY_BASELINE.md` §5 | `finalizer != approver`, not configurable off; break-glass activation, grants, endpoints, flags and runtime bypasses disabled for Phase 1A. Resolves DOC-CONFLICT-021 (Approved 2026-07-20). |
| POL-005, Approved | Phase 1A break-glass disabled. M3 therefore builds no break-glass route and no `break_glass.*` grant; `15_Agent_Implementation_Plan.md:633` and `12_Security_RBAC_Audit.md:621` both point emergency access at that process, and the approved answer for Phase 1A is that it is off. |
| `docs/governance/status_catalog.yaml` (approved 2026-08-01) | Canonical status values. `identity_account` is `canonical: null` with seven aliases (`:651-657`) — see section 2.3. |

## 2.2 What M2 already shipped, and therefore what M3 must not rebuild

M3 starts further along than the milestone text assumes, because M2's schema slices built the
identity foundation deliberately so that M3 "does not have to invent it while also writing login"
(`app/db/models/identity.py:21-22`).

Already present and tested:

- `admin_users` and `trader_users` as **two tables, not one with a type flag**, each with
  `password_hash`, `status`, `security_stamp_version`, `failed_login_count`, `locked_until`,
  `last_login_at`, `password_changed_at`.
- `roles`, `permissions`, `role_permissions`, `admin_user_roles` with the partial unique index for
  one active grant, and the canonical catalogue **seeded** by migration `_0008`.
- `auth_sessions` with `secret_hash` (never the secret), the XOR check that exactly one of
  `admin_user_id`/`trader_user_id` is set, `auth_level`, `expires_at`, `revoked_at`,
  `revocation_reason`, `security_stamp_version`, and the replaced-session pointer.
- `auth_events` as an append-only security-event table, separate from `audit_logs`.
- `recent_auth_contexts` with consumption columns.
- Column-level `GRANT` such that runtime roles cannot mutate append-only records.

So M3 writes **behaviour**, not schema — with two exceptions, both forced, both in slice 1
(section 2.4).

## 2.3 Three Open conflicts whose gate is M3, and what this plan decides

`docs/governance/CONFLICT_REGISTER.md` records three Open conflicts whose blocking gate names M3.
None can be deferred: each one is a precondition of a capability `15_Agent_Implementation_Plan.md:604-619`
requires. Each is decided here with the reasoning, for approval in the pull request.

### DOC-CONFLICT-023 — authentication route and identity-domain separation

**The conflict** (`CONFLICT_REGISTER.md:48`): `05_API_Specification.md:743-756` shows one login
route, `POST /api/v1/auth/login`, with `user_type: admin | trader` in the request body.
`12_Security_RBAC_Audit.md:305-314` requires separate login routes, application audiences, session
audiences, permission evaluation, route middleware, response DTOs, navigation/bundles, and
rate-limit policies. The recorded direction is: "Never trust `user_type` to select authority.
Authentication must derive and enforce audience/domain server-side; final routes/transport remain
behind ADR-001." ADR-001 is now Approved, so the remaining half — the route shape — is decidable.

**Decision: two routes, `POST /api/v1/auth/admin/login` and `POST /api/v1/auth/trader/login`. The
audience is a property of the route and of the session row, never of a request field.**
`05_API_Specification.md`'s single route with `user_type` is superseded, not aliased.

Four reasons.

A body field cannot carry authority, but it can carry **which authority is evaluated**, and that is
enough to be wrong. `user_type` selects the identity table to authenticate against. On its own that
is not a privilege escalation — an attacker still needs valid admin credentials. What it does is
make the audience a request parameter, so the separation doc 12 requires lives inside a handler
branch where no test can observe it from the outside.

**Doc 12 requires separate route middleware, and middleware attaches to routes.** One route that
branches internally cannot have two rate-limit policies, two cookie scopes and two DTO shapes
without reimplementing routing inside the handler.

**The cookie must be audience-scoped, and the browser must do the scoping.** Two routes issue two
distinctly named cookies, so a trader credential is **not sent** to an admin endpoint by the browser.
With one route and one cookie name, doc 12's requirement that "a trader session must not be accepted
as an internal session" (`:316`) degrades to a server-side check somebody can forget. Not sending the
credential is a stronger control than checking it.

> **Corrected 2026-08-09, before slice 4 was written.** This paragraph originally said the two
> cookies would be scoped by **path** — `gp_admin_session` on `/api/v1/admin`. That path does not
> exist. `05_API_Specification.md` is resource-first (`/payment-requests`, `/traders`, `/files`,
> `/auth`) and has no audience segment, and `app/api/router.py` mounts everything under one
> `/api/v1`. Worse, a path-scoped cookie would not be sent to the shared `/auth/me`, `/auth/logout`
> and `/auth/sessions` routes this same plan defines, so `me` would read as unauthenticated and
> logout could not revoke.
>
> The isolation axis this deployment actually has is the **host**. `infra/nginx/conf.d/local.conf`
> serves the trader app on `trader.localhost` and the admin app on `admin.localhost`, each with its
> own `/api/` proxy to the same backend, so each app is same-origin with the API and the two apps are
> different origins from each other. A **host-only** cookie — no `Domain` attribute — is therefore
> never sent to the sibling app, whatever its path.
>
> Slice 4 uses the `__Host-` cookie prefix, which is not decoration: the browser refuses to store a
> `__Host-` cookie unless it is `Secure`, carries **no** `Domain`, and has `Path=/`. That makes
> host-only scoping structurally enforced by the client rather than a server-side attribute a later
> edit could add. The footgun it closes is concrete — `server_name trader.localhost localhost` binds
> the trader app to bare `localhost` too, so a cookie set with `Domain=localhost` would be delivered
> to `admin.localhost`, and in production `Domain=example.ir` would leak the trader cookie to the
> admin app.
>
> Two consequences recorded rather than quietly dropped. **`SameSite` provides no separation between
> the two apps** — they are the same site — so it defends against third-party sites only and must not
> be cited as audience isolation. And **the CORS allowlist this plan promised at slice 4 is dead
> configuration**: no browser request is cross-origin under this topology, `connect-src 'self'` is
> already set, and middleware that never fires is worse than none because a test asserting it would
> be testing an unreachable path. It is not added; it becomes real only if the API is ever given its
> own hostname.

**The session row already records the audience structurally.** `auth_sessions` has the XOR check
that exactly one of `admin_user_id`/`trader_user_id` is set. An audience guard can therefore compare
the route's expected actor column against the session's populated column, so a mismatch is a `NULL`
rather than an unequal string. Comparing a string like `"admin"` reintroduces the class of bug the
XOR check was written to remove.

**Aliasing is refused deliberately.** Keeping `POST /auth/login` with `user_type` as a compatibility
route would reintroduce exactly the property being removed, and unlike a permission alias it cannot
be made narrower-but-safe: it either accepts the field or it does not. DOC-CONFLICT-023's recorded
direction says the final routes were never frozen, so this supersedes rather than deviates.

**Consequence for `openapi.json` and the generated TypeScript client:** both regenerate in slice 4.
`pnpm openapi:check` failed twice in M2 on exactly this omission; the plan lists it as an explicit
step rather than an implied one.

### DOC-CONFLICT-024 — trader and account status model

**The conflict** (`CONFLICT_REGISTER.md:49`): `04_Database_Schema.md:458-459` gives `traders` two
separate columns, `operational_status` (`active`/`inactive`/`suspended`/`blocked`) and
`approval_status` (`pending_approval`/`approved`/`rejected`). `05_API_Specification.md` exposes a
combined `status`. `12_Security_RBAC_Audit.md:416-438` adds account states `locked`,
`recovery_required` and `deactivated`. Recorded direction: "Model trader approval, trader operation,
and login-account security as separate concepts; expose an explicit projection rather than one
mutable canonical status."

**Decision: three axes, each owned by exactly one column, and a computed projection that is never
stored.**

| Axis | Column | Values | Question it answers |
|---|---|---|---|
| Business relationship | `traders.approval_status` | `pending_approval`, `approved`, `rejected` | Has this business been accepted as a counterparty? |
| Business operation | `traders.operational_status` | `active`, `inactive`, `suspended`, `blocked` | May this business transact today? |
| Login account | `admin_users.status`, `trader_users.status` | see DOC-CONFLICT-037 below | May this human sign in, and with what restriction? |

The projection the API returns is derived at read time from all three plus `locked_until`. It is
**computed, never persisted**, because a stored combined status is a fourth copy of three facts and
would drift from them — the failure this repository has now recorded five times. `traders` gets no
`status` column at all, so the drift is unrepresentable rather than merely tested for.

The axes are genuinely independent, which is what makes one column wrong: a trader business can be
`approved` and `suspended` at once (accepted counterparty, temporarily barred); one of a business's
two contacts can have a suspended **login** while the business itself keeps transacting through the
other. A single status cannot express either.

### DOC-CONFLICT-037 — the `identity_account` status value set

**The conflict** (`CONFLICT_REGISTER.md:63`): `status_catalog.yaml:651-657` records
`identity_account` as `canonical: null` with seven aliases — `pending`, `active`, `suspended`,
`inactive`, `locked`, `recovery_required`, `deactivated` — and notes that document 06 canonicalises
trader business onboarding rather than the authentication-account lifecycle.
`04_Database_Schema.md:349` names four (`pending`, `active`, `suspended`, `inactive`);
`12_Security_RBAC_Audit.md:420-427` recommends six (`pending_approval`, `active`, `suspended`,
`locked`, `recovery_required`, `deactivated`). The recorded interim rule is that both `status`
columns ship with **no value CHECK**, application-enforced, and that "the CHECK is added by
expand/contract once the lifecycle is approved."

M3 is where that approval has to happen: `15_Agent_Implementation_Plan.md:611` requires "account
suspension and lock behavior" and `:608` requires "pending-approval access for traders", and neither
can be implemented against an undecided value set.

**Decision: four values — `active`, `suspended`, `recovery_required`, `deactivated`.** Three of the
seven aliases are rejected, each for a reason that removes a duplicate source of truth rather than a
feature.

**`locked` is rejected.** Both identity tables already carry `locked_until TIMESTAMPTZ`
(`app/db/models/identity.py:97-99`). Lockout is a time-bounded fact that ends by itself; a status
value is not, and would need a scheduled job to leave. Doc 12's own gloss —`locked` "blocks
authentication temporarily or until reviewed" (`:434`) — describes a timestamp. Storing it twice
means a row can be `status = 'active'` with `locked_until` in the future, or `status = 'locked'`
with `locked_until` in the past, and no constraint can say which is authoritative. Lock is therefore
**derived**: `locked_until IS NOT NULL AND locked_until > now()`.

**`pending` / `pending_approval` is rejected on the account axis.** It duplicates
`traders.approval_status`. The login account is not pending approval; the **business** is. This is
DOC-CONFLICT-024's decision applied consistently — putting the trader's approval state on the
trader's user row is precisely the axis-mixing that conflict exists to stop. A trader user of a
`pending_approval` business may sign in and reach only the pending-account experience
(`12_Security_RBAC_Audit.md:431`); the restriction comes from the business axis, where it is true.

**`inactive` is rejected in favour of `deactivated`.** Same meaning, and doc 12's name is the one
that does not collide: `inactive` is already a value of `traders.operational_status`
(`04_Database_Schema.md:458`), so reusing it on the account axis makes a log line or a bug report
ambiguous about which axis it refers to — the exact confusion DOC-CONFLICT-024 is about.

`recovery_required` is **kept**, and it encodes a policy, so the policy is stated: an administrative
password reset sets `recovery_required`, which permits only the credential-recovery flow and forces
a password change before any other request succeeds. `12_Security_RBAC_Audit.md:397` requires the
production policy to decide "whether forced rotation is required after an administrative reset"; for
a settlement platform the answer is yes, because the alternative is that an administrator
indefinitely knows a working credential for another person's financially-authorised account.

**Consequences:**

1. `status_catalog.yaml` is amended: `identity_account` becomes canonical with these four values,
   and the three rejected aliases are recorded with the reason each was rejected. This edits an
   **approved** catalogue (`approved_phase_1a`) and therefore needs recorded owner approval on the
   same convention as ADR-001.
2. DOC-CONFLICT-037 moves to Resolved, and its interim "no value CHECK" rule expires — the CHECK is
   added in slice 1's migration on both identity tables.
3. `uq_trader_users_primary_contact` currently reads `WHERE is_primary = TRUE AND status <> 'inactive'`
   (`app/db/models/identity.py:176`). With `inactive` gone, that predicate matches every row and the
   index silently constrains rows it was written to exclude. It must change in the same migration —
   see section 2.4, defect 2.

## 2.4 Two defects M2 left in the identity schema, found while planning this

Both are in `trader_users`, both were invisible to M2's gates because the table they depend on did
not exist yet, and both must be fixed **before** any code creates a trader — which is slice 9. They
are slice 1 because a migration is cheaper than a data repair.

### Defect 1 — `trader_users.trader_id` is missing, so ownership has nothing to hang on

`04_Database_Schema.md:345` requires `trader_id UUID`, required, `FK traders`.
`12_Security_RBAC_Audit.md:334` lists "owning trader relationship for trader users" among the fields
identity records must support. The column does not exist, because `traders` does not exist: doc 04
places `traders` at `:450-476`, and `docs/governance/TRACEABILITY_MATRIX.md:25` assigns that range
to M3 ("`:450-528` adds trader ownership records used by identity scope"). M2 shipping
`trader_users` without it was correct sequencing.

It is nonetheless load-bearing for every ownership guard in this milestone: `ActorContext.trader_id`
has no source until this column exists, and QA's mandatory IDOR case "Trader A submits `trader_id`
belonging to B" (`14_Testing_QA_Acceptance.md:1280`) cannot even be written.

**Fix:** slice 1 creates `traders` per doc 04 §7.1 and adds `trader_users.trader_id` as
`NOT NULL` with a foreign key. No environment can hold `trader_users` rows — there is no
registration flow before slice 9, and `12_Security_RBAC_Audit.md:386` forbids seeded credentials in
migrations — so the column is added `NOT NULL` directly. The migration asserts the table is empty
first and aborts with a readable message if it is not, rather than discovering it through a
constraint violation.

### Defect 2 — the primary-contact index is a global singleton, not one per business

`04_Database_Schema.md:360-362` specifies:

```sql
CREATE UNIQUE INDEX uq_trader_users_one_primary
ON trader_users(trader_id)
WHERE is_primary = TRUE AND status <> 'inactive';
```

What shipped (`app/db/models/identity.py:172-177`, migration `_0007:178`) indexes `is_primary`
instead of `trader_id`, with the same predicate. Because `trader_id` did not exist, the index key
became the flag itself — so the constraint enforced is **"at most one primary trader contact in the
entire system"** rather than "at most one per trader business". The model's own comment describes the
intended per-business rule (`:145-147`), so the divergence is between the code and its own stated
intent, not a judgement call.

Nothing caught it. `test_schema_matches_models.py` compares the migration against the model and both
say `is_primary`, so they agree with each other and disagree with the specification. The constraint
tests assert the index rejects a duplicate, which it does — the singleton rejects duplicates
enthusiastically. And no test creates two trader businesses, because there are none.

The failure it would have produced is worth stating, because it is the shape that reaches
production: registration would work perfectly for the first trader and fail for the second with a
unique-violation on a column the caller never set. Registration is slice 9 of this plan, so the
defect had roughly one milestone left to live.

**Fix:** slice 1 drops the index and creates the specified one, keyed on `trader_id`, with the
predicate updated to `status <> 'deactivated'` per section 2.3, under doc 04's name
`uq_trader_users_one_primary`. The regression test creates **two** trader businesses and asserts
each may have its own primary contact — which is the test whose absence allowed this.

**The lesson recorded:** a constraint whose key column does not exist yet degrades into a different
constraint that still passes its tests. Slice 1 adds a structural gate for the class, not just a fix
for the instance: every index and CHECK that `04_Database_Schema.md` states in SQL is compared, by
name and by key columns, against what the database actually has, so a doc-specified constraint that
is absent or differently keyed fails rather than passing quietly.

## 2.5 What M3 leaves open on purpose

| Open item | Why M3 does not decide it | How M3 stays honest about it |
|---|---|---|
| **ADR-009** — assurance factor and step-up duration | Its gate is M7's approval production gate and M12/M13, not M3 (`TRACEABILITY_MATRIX.md:25`). The factor choice depends on operational facts about the deployment — SMS deliverability, whether the people holding manager authority carry smartphones — that are the owner's knowledge, not a technical judgement. | Slice 8 builds the recent-auth abstraction with `password` as the only registered factor and the factor behind an interface, so adding one is a registration, not a rewrite. The evidence emitter records the factor decision as unfilled with this reason. |
| **ADR-SEC-002** — idle and absolute session timeouts | A subset of ADR-001 that ADR-001's approval explicitly did not satisfy. `12_Security_RBAC_Audit.md:458` states the timeouts are ADR decisions and gives only the invariants. | Timeouts are configuration with fail-closed defaults (admin stricter than trader, per `:460`) and are validated at startup. Tests assert the **invariants** doc 12 does state — a session cannot outlive deactivation or a security-stamp change (`:461`), expiry is server-side (`:462`), expired sessions produce `401 UNAUTHENTICATED` (`:464`) — never a specific duration. |
| **OPS-003** — cookie scope, origins, TLS/HSTS | Deployment topology, not application behaviour. | Cookie `Domain`/`Secure` and the CORS origin allowlist are configuration with no permissive default; a missing origin list fails startup rather than allowing all. |
| **Password policy numbers** — minimum length, compromised-password rejection, lockout threshold, backoff curve | `12_Security_RBAC_Audit.md:390-397` requires the *production policy* to define these; it is a business/security decision with an operational cost (support calls). | Configuration with defensible fail-closed defaults, recorded in the plan and in the release evidence as provisional. Tests assert the mechanism (a threshold exists, backoff grows, state is durable) and never the number. |
| **`support_operator`** | `15_Agent_Implementation_Plan.md:630` marks it optional and `12_Security_RBAC_Audit.md:618` marks it "Internal optional". | Not seeded. Adding an unrequested role with no defined permission set would be inventing authority. |
| **Break-glass** | POL-005 Approved: disabled for Phase 1A. | No route, no grant, no flag. Slice 8 adds a test that no seeded role holds `break_glass.activate` and that no route declares it — so the disabled state is enforced rather than merely unimplemented. |

---

# 3. The slice plan

Ten slices. Each is one pull request, each leaves `main` green, and each ends with the negative
controls that prove its own tests can fail. The order is a dependency order: nothing in slice *n*
can be written without slice *n-1*, except where noted.

## Slice 1 — Trader ownership root, the two schema defects, and the account-status decision

> **Revision, 2026-08-08, after reading the code this slice touches.** Three things
> changed once the conventions were checked against the repository rather than assumed,
> and all three are recorded here rather than absorbed silently.
>
> **`DB-SPEC-001` moves to its own slice (1B).** Comparing every constraint doc 04 states
> in SQL against the database is the right gate, and building it surfaced roughly forty
> pre-existing divergences across tables M2 shipped — four indexes renamed against
> DOC-CONFLICT-042's rule, two narrowed silently, one absent, about fifteen tables whose
> indexes belong to later milestones, and a handful of objects the codebase added that
> doc 04 never states. Each needs a disposition, and none of it is M3. Bundling it here
> would triple the slice and bury the defect fix inside an audit. Slice 1 instead proves
> the same defect **behaviourally**, from the outside, with a test that cannot be made
> green by any exemption list: two trader businesses may each have their own primary
> contact.
>
> **DOC-CONFLICT-024 gets its structural half only.** The approved `status_catalog.yaml`
> records one `trader` aggregate carrying document 06's single five-state machine, plus
> `blocked` and `approved` as unresolved aliases it says in terms must not be collapsed
> without policy approval. Document 04's two columns do not partition that set, so
> enumerating either would decide — from a migration — whether `blocked` folds into
> `suspended`. That is M5's trader lifecycle, and it is what 024's own Blocks column says.
> M3 therefore ships the structure (three axes, no stored projection, no `status` column
> on `traders`) and pins the absence of both value CHECKs.
>
> **DOC-CONFLICT-023 stays Open until slice 4.** The decision is recorded and merged, but
> nothing enforces it until the two login routes and `SEC-AUD-002` exist. Marking it
> Resolved in a slice that touches no route would make the register's status mean
> "somebody wrote it down" rather than "the codebase holds to it".

### Goal

Give ownership something to hang on, fix what M2 left wrong before any code depends on it, and
close the three conflicts from section 2.3 so the rest of M3 is not building on undecided values.

### What it changes

- Migration `20260808_0013_trader_ownership_and_account_status.py`:
  - creates `traders` per `04_Database_Schema.md:452-476` — including
    `CHECK (credit_limit_irr IS NULL OR credit_limit_irr >= 0)`, `UNIQUE(primary_phone)` and
    `idx_traders_status_approval` — and **no** `current_balance_irr`, which `:469` prohibits without
    a ledger, and no combined `status` column per section 2.3;
  - adds `trader_users.trader_id NOT NULL` with the foreign key, aborting with a readable message if
    the table is non-empty;
  - drops `uq_trader_users_primary_contact` and creates `uq_trader_users_one_primary` on
    `trader_users(trader_id) WHERE is_primary = TRUE AND status <> 'deactivated'`;
  - adds the `identity_account` value CHECK to `admin_users.status` and `trader_users.status`.
- `app/db/models/identity.py`: the `trader_id` relationship, the corrected index, the status CHECK,
  and the account-status value tuple as the single Python source.
- `app/db/models/trader.py`: the `Trader` model.
- Governance: `status_catalog.yaml` `identity_account` becomes canonical with four values and three
  recorded rejections; DOC-CONFLICT-023, 024 and 037 move to Resolved with the section 2.3 reasoning;
  `M0_MANIFEST.json` hashes regenerated; the derived counts follow automatically because
  `test_governance_counts_reconcile.py` now gates all five restatement sites.
- `tests/backend/test_traceability.py`: read every `docs/handoff/M*_IMPLEMENTATION_PLAN.md` rather
  than the hard-wired M2 path, and add the `UI` prefix. This needs one addition, not just a glob:
  the gate requires every obligation to be cited by a test, and M3's are discharged slice by slice,
  so pointing it at this plan unchanged would fail on the day it lands with eighty uncited ids. The
  gate therefore reads a per-plan **milestone state** — `complete` or `in progress` — and for a plan
  in progress requires only that obligations belonging to *merged* slices are cited, while still
  rejecting an invented prefix or a duplicate id anywhere. Without this, M3's obligations sit outside
  the coverage gate entirely, which is the "written once, gated nowhere" failure the gate exists for;
  with a naive glob, the gate gets disabled in week one, which is worse.

### What proves it

- `DB-TRADER-001` — `traders` matches doc 04 §7.1 column for column, and has no `current_balance_irr`
  and no combined `status`.
- `DB-OWN-001` — `trader_users.trader_id` is `NOT NULL` and its foreign key rejects an unknown trader.
- `DB-PRIMARY-001` — **two** trader businesses may each have their own primary contact, and a second
  primary within one business is rejected. The regression test for defect 2.
- `DB-PRIMARY-002` — a `deactivated` former primary does not block appointing a new one, and the
  predicate names a value the CHECK admits.
- `DB-ACCT-001` — each of the four account values is accepted; each of the three rejected aliases is
  refused by the CHECK.
- `DB-PRIMARY-003` — the predicate of `uq_trader_users_one_primary` names a value
  `ck_trader_users_status` admits. Guard-the-guard: a predicate referencing a value no row may hold
  is not a narrower index, it is a second condition that can never be false.
- `SEED-ACCT-001` — no migration inserts a credential (`12_Security_RBAC_Audit.md:386`).

`DB-SPEC-001` and `TRACE-PLAN-001` move to slice 1B, for the reason recorded in the revision note
above. Named here so the deferral is visible rather than a quiet omission.

## Slice 1B — The specification is compared against, and an obligation that never had a definition

### Goal

The two obligations slice 1 deferred. Recorded as a section for the same reason 10B–10D are: an
owner with no section is an owner nobody can review.

### What it changes

- `tests/integration/test_schema_matches_the_specification.py` — the comparison **M2 never made**.
  `test_schema_matches_models.py` compares the database to `Base.metadata`; `test_constraint_names.py`
  compares names to what the models compile to. Neither has ever opened `04_Database_Schema.md`. This
  slice's own retrospective at `M3_IMPLEMENTATION_PLAN.md:1727-1731` says why that matters: "a
  constraint the specification states and the code does not is the one shape a
  model-versus-migration comparison can never see, because both sides can be wrong together."
- `tests/backend/test_governance_evidence_exists.py` — a definition for `TRACE-PLAN-001`.
- `CONFLICT_REGISTER.md` gains DOC-CONFLICT-044 and a correction to DOC-CONFLICT-042.

### The finding, which is not "forty divergences"

The estimate in slice 1's revision note was made before the gate existed. Built and run, it produces
**nine**, and the shape matters more than the count:

- **Six indexes renamed against an approved resolution.** DOC-CONFLICT-042 was approved on
  2026-08-06 with the rule that an index document 04 names keeps that name verbatim. Every one of
  the six exists and does the specified work under another name, so nothing is unindexed and no
  query is slow. What was wrong is that an approved rule went unfollowed and nothing reported it.
- **Two of those six also name columns the schema does not have** — doc 04 writes
  `file_links(entity_type, entity_id, link_type)` and `audit_logs(event_type, created_at)` against
  the real `resource_type/resource_id/link_role` and `action/occurred_at`. The doc-04 name could not
  be adopted verbatim even if somebody wanted to. That is a documentation correction owed to
  document 04's owner, and a different repair from the other four.
- **One genuine absence.** No index covers `admin_users(status)` under any name. Recorded rather
  than added: the staff list is unpaged over tens of rows by a decision `list_admin_users` already
  records, so a sequential scan is cheaper than the index today.
- **Two predicate divergences, both already decided.** `uq_trader_users_one_primary` names
  `'deactivated'` where doc 04 writes `'inactive'` — DOC-CONFLICT-037's approved four-value account
  set, which doc 04 predates, and whose doc-04 predicate would now be a condition no row can satisfy.
  `idx_outbox_dispatch` diverges for a reason the model's own docstring already states.

### `TRACE-PLAN-001` had no definition, anywhere

It appeared exactly twice in the repository: in the line deferring it, and in the pending ledger
recording that deferral. Two milestones carried it as a name with an owner and no content.

So slice 1B defines it from the defect this slice found rather than from the name. **A governance
record's evidence must name something that exists.** DOC-CONFLICT-042's approved resolution cited
`test_constraint_names.py` as asserting the doc-04 names verbatim; that test compares against the
models and has never read document 04. The rule was approved, recorded as enforced, and unenforced.

The damage is specific: a reviewer checking whether a rule is enforced finds a named test, sees it
green, and stops. A wrong evidence citation converts an unchecked rule into an apparently-checked
one, which is worse than no citation — the second invites the check that the first prevents.

### `SEED-ACCT-001` is now registered

DOC-CONFLICT-044. Document 12:386 forbids seeded development credentials "in production images or
migrations"; document 13:907 permits initial administrator creation by "a controlled command **or
migration task**". This repository's gate forbids any identity `INSERT` in any migration — the
stricter reading, chosen silently in slice 1 and never registered. Slice 8B's command makes the
question moot in practice, so nothing is blocked; what is owed is the owner deciding whether the
migration route is permitted at all. Adding the row moves the register to 44 conflicts and 23 open,
which four other sites restate — the header sentence, the summary table, `README.md`,
`TRACEABILITY_MATRIX.md` and `M0_MANIFEST.json`. `test_governance_counts_reconcile.py` named every
one of them.

### What proves it

- `DB-SPEC-001` — every index document 04 states exists on the table it names, with the uniqueness it
  states and a partial predicate naming the same identifiers and literals. Divergences are a ledger
  with a disposition each, and `test_no_disposition_is_stale` fails on an entry whose divergence has
  been fixed, so the ledger cannot accumulate permissions for solved problems.
- `TRACE-PLAN-001` — every file `CONFLICT_REGISTER.md` cites as evidence exists, and a row citing a
  test names one the suite collects. DOC-CONFLICT-042's corrected row is pinned by name, because the
  general check cannot see that failure: the file it wrongly cited exists and is collected.

### Negative controls

Break the doc-04 parser and confirm the floor fires rather than an empty comparison passing. Remove a
disposition and confirm its divergence is reported. Add a disposition for an index that matches the
specification and confirm `test_no_disposition_is_stale` names it. Point DOC-CONFLICT-042's evidence
back at `test_constraint_names.py` and confirm the pinned test fails — that is the whole obligation,
and the general structural checks pass over it.

### Negative controls

Re-key `uq_trader_users_one_primary` back to `is_primary` and confirm `DB-PRIMARY-001` fails — the
control that proves the fix is what the test detects, not a coincidence. Restore the predicate to
`status <> 'inactive'` and confirm `DB-PRIMARY-003` fails, because that is the coupling between the
two halves of the decision. Remove a value from `ACCOUNT_STATUSES` without touching the catalogue and
confirm `DB-ACCT-001` and the status-catalogue drift gate both react.

## Slice 2 — Password hashing, the ActorContext, and the session store

### Goal

Everything authentication needs with no HTTP in it, so the security properties are tested at the
service boundary before a cookie exists to confuse them.

### What it changes

- `app/security/passwords.py`: Argon2id via `argon2-cffi`
  (`12_Security_RBAC_Audit.md:381` prefers it), parameters in config with fail-closed minimums,
  needs-rehash detection on parameter change, and a maximum accepted length so a long password
  cannot be a denial-of-service vector (`:394`). Never logs, never returns, never serializes a hash
  (`:382-383`).
- `app/security/actor.py`: the frozen `ActorContext` — `actor_type`, `actor_id`, `audience`,
  `session_id`, `trader_id | None`, `roles`, `permissions`, `auth_level`, `security_stamp_version`.
  Transport-neutral by construction (`:377`): no request, cookie or claim type is importable here.
- `app/security/sessions.py`: create, validate, revoke, and rotate. The session secret is generated
  with `secrets.token_urlsafe` and stored only as a SHA-256 hash. **A fast hash is correct here and
  a slow one would be wrong**: the secret is 256 bits of uniform randomness, so there is no
  dictionary to slow down, and Argon2 on the session path would add its work factor to every
  authenticated request.
- Validation re-reads the identity row on every protected request and compares
  `security_stamp_version`, because `12_Security_RBAC_Audit.md:438` requires status revalidation and
  forbids relying on a stale claim.
- `app/security/events.py`: the `auth_events` writer, with the redaction rule from
  `04_Database_Schema.md:444` — no plaintext password, OTP, token or full secret — enforced by an
  allowlist of recordable fields rather than by a denylist of forbidden ones.

### What proves it

- `SEC-PWD-001` — a correct password verifies, a wrong one does not, and the stored hash is not the
  password.
- `SEC-PWD-002` — hashing the same password twice yields different encodings (salted), and both
  verify.
- `SEC-PWD-003` — a password above the maximum length is rejected before hashing, not after.
- `SEC-PWD-004` — raising the parameters marks existing hashes as needing rehash without
  invalidating them.
- `SEC-SESS-001` — a created session validates; its raw secret appears nowhere in the row.
- `SEC-SESS-002` — an expired session fails validation; expiry is evaluated server-side from
  `expires_at`, not from anything the caller sends.
- `SEC-SESS-003` — a revoked session fails validation and the reason is recorded.
- `SEC-STAMP-002` — bumping the identity's `security_stamp_version` invalidates every live session
  for that identity on the next request. The mechanism behind every revocation trigger in
  `12_Security_RBAC_Audit.md:468-477`.

  **Renumbered in slice 8B, and moved to pending, because the previous identifier was doing two jobs
  and the obligation was reporting itself proved.** `M2_IMPLEMENTATION_PLAN.md:932` claims the same
  string for its own slice, and coverage is keyed by exact identifier, so M2's citations discharged
  this obligation as a side-effect. (The superseded id is not written here: a mention inside a "What
  proves it" section is itself a claim, which is how the first attempt at this correction recreated
  the collision it was fixing.) Worse, the thing the sentence describes has no producer:
  `security_stamp_version` is
  read, copied into sessions and CHECKed positive in thirteen places across `app/`, and
  **incremented in none of them**. The comparison exists; nothing makes the two values differ. Slice
  8C writes the first increment, so that is where this can first fail.
- `SEC-EVENT-001` — a failed login writes an `auth_events` row; the row contains no credential
  material, proven by asserting the password string is absent from the serialized row.
- `SVC-ACTOR-001` — `app/security/actor.py` imports nothing from `fastapi`, `starlette` or
  `app.api`, so transport-neutrality is structural.

### Negative controls

Store the session secret in place of its hash and confirm `SEC-SESS-001` fails. Add the password to
the event metadata and confirm `SEC-EVENT-001` names the field.

The control this slice listed for the security stamp — "skip the security-stamp comparison and
confirm it fails" — **cannot fail today**, and slice 8B recorded why rather than leaving it as a
claim. Deleting the comparison changes nothing observable, because no code path ever makes the two
values differ: the comparison is between a number copied into the session at login and the same
number on the identity, and nothing increments either. The control becomes real in slice 8C, at the
same moment the first increment is written.

## Slice 3 — Account states, lockout, and authentication rate limiting

### Goal

The behaviour behind `15_Agent_Implementation_Plan.md:611` — "account suspension and lock behavior"
— and `:619` — "rate limiting for authentication" — on the four values slice 1 decided.

### What it changes

- `app/security/account_state.py`: what each of the four values permits, and the derived lock from
  `locked_until` (section 2.3). One function answers "may this identity authenticate, and if not
  why", and the login path has no second opinion.
- Failed-login counting and temporary lock in PostgreSQL, not Redis. `infra/redis/redis.conf` sets
  `appendonly no` and `save ""`, so a Redis-only counter resets on restart and an attacker waits for
  one — the reason the columns are on the identity tables
  (`app/db/models/identity.py:91-93`). `12_Security_RBAC_Audit.md:488` states the requirement.
- Rate limiting by normalized identifier **and** network source, keyed by HMAC of each rather than
  the value, per `:483` ("privacy-conscious keys"). Redis carries the sliding window because losing
  it costs only rate-limit history; the durable lock is unaffected.
- Generic `INVALID_CREDENTIALS` for every failure reason (`:403-414`), including suspended,
  deactivated and unknown identity, so the response cannot be used to enumerate accounts. The
  specific reason goes to `auth_events`, never to the client.
- `recovery_required` permits only the credential-recovery flow; every other request fails.

### What proves it

- `SEC-ACCT-001` — `active` authenticates; `suspended`, `recovery_required` and `deactivated` do not.
- `SEC-ACCT-002` — suspension takes effect on the **next request of a live session**, not only at
  next login, via the security-stamp bump.
- `SEC-ACCT-003` — a `recovery_required` account may call only the recovery endpoint; an otherwise
  valid protected request fails.
- `SEC-LOCK-001` — the configured number of failures locks the account; `locked_until` in the future
  refuses authentication with correct credentials.
- `SEC-LOCK-002` — the lock expires on its own with no scheduled job, which is the property that
  made `locked` unnecessary as a status value.
- `SEC-LOCK-003` — the durable lock survives a Redis flush. The test for `:488`.
- `SEC-ENUM-001` — unknown identity, wrong password, suspended and deactivated produce byte-identical
  response bodies and the same status code.
- `SEC-RATE-001` — the limiter blocks by identifier and by source independently; stored keys contain
  neither the identifier nor the raw address.
- `AUD-EVENT-001` — every outcome in `SEC-ENUM-001` writes a distinguishable `auth_events` row, so
  the information the client is denied is still available to an investigator.

### Negative controls

Move the failed-login counter into Redis and confirm `SEC-LOCK-003` fails. Return a distinct message
for a suspended account and confirm `SEC-ENUM-001` fails. Store the raw identifier as the rate-limit
key and confirm `SEC-RATE-001` names it.

## Slice 4 — Cookie transport, CSRF, and the two login routes

### Goal

ADR-001 made concrete, and DOC-CONFLICT-023 implemented: the first slice where a browser can sign in.

### What it changes

- `POST /api/v1/auth/admin/login`, `POST /api/v1/auth/trader/login` (section 2.3); `GET /auth/me`
  (`05_API_Specification.md:791`), `POST /auth/logout` (`:799`, idempotent by definition),
  `GET /auth/sessions` (`:807`), `POST /auth/sessions/{session_id}/revoke` (`:813`).
- Audience-scoped cookies: `HttpOnly`, `Secure`, `SameSite=Strict`, distinct names, distinct paths.
  `Strict` rather than `Lax` because Phase 1A has no cross-site entry flow that needs the cookie on
  a top-level navigation, and `Strict` is the option that also refuses it on a cross-site `GET`.
- CSRF bound to the session and validated server-side (`12_Security_RBAC_Audit.md:495`) — not a
  stateless double-submit, which validates that two attacker-writable values match. The token is
  derived per session and required in `X-CSRF-Token` on every unsafe method.
- CORS is **not** configured, and the omission is the decision: every browser request is same-origin
  under the real nginx topology, so an allowlist would never fire. `:496` is satisfied today by
  `connect-src 'self'` plus the absence of any cross-origin surface, and re-examined the moment the
  API gets a hostname of its own.
- The audience guard compares the route's expected actor column against the session row's populated
  column, so a cross-audience session is a `NULL`, not an unequal string.
- `openapi.json` and the generated TypeScript client regenerate in this slice, and
  `pnpm openapi:check` runs in the same pull request. M2 failed CI twice on exactly this.

### What proves it

- `API-AUTH-001` — admin login sets the admin cookie and no trader cookie; trader login the reverse.
- `API-AUTH-002` — the cookie carries `HttpOnly`, `Secure` and `SameSite=Strict`, and its value is
  not the session id.
- `SEC-AUD-001` — a trader session presented to an internal endpoint is rejected; an admin session
  on a trader-only endpoint is rejected. Doc 12:316 in both directions.
- `SEC-AUD-002` — no request body field can select the audience: there is no `user_type` in any
  login schema, asserted against the generated OpenAPI document rather than the handler source.
- `SEC-CSRF-001` — an unsafe method without the header is rejected; with a token from a **different**
  session it is rejected; with the correct token it succeeds.
- `SEC-CSRF-002` — no route registered under `/api/v1` uses `GET` to change state, per `:497`.
  Structural, over the router.
- `API-AUTH-003` — `POST /auth/logout` twice succeeds twice and leaves the session revoked once.
- `API-AUTH-004` — `GET /auth/me` returns roles, permissions and, for a trader, the own `trader_id`
  (`05_API_Specification.md:794`), and never a password hash.
- `SEC-LEAK-001` — no session secret appears in a URL, a log line, or a response body
  (`14_Testing_QA_Acceptance.md:1310`).
- `CI-OPENAPI-001` — the committed OpenAPI document and TypeScript client match the routes.

### Negative controls

Drop `HttpOnly` and confirm `API-AUTH-002` fails. Accept the trader cookie on an admin route and
confirm `SEC-AUD-001` fails. Add a `user_type` field to the login schema and confirm `SEC-AUD-002`
fails. Replace session-bound CSRF with a double-submit and confirm `SEC-CSRF-001`'s cross-session
case fails.

## Slice 5 — Permission guards

### Goal

`15_Agent_Implementation_Plan.md:612` — "backend permission guards" — evaluated from the seeded
catalogue, failing closed on anything unknown.

### What it changes

- `app/security/permissions.py`: resolve an identity's permissions through
  `admin_user_roles → role_permissions → permissions`, honouring `revoked_at`. Trader access is
  **not** resolved this way — `04_Database_Schema.md:405` states trader access is determined by
  authenticated identity and ownership scope, so a trader's permission set is fixed by audience and
  a trader row in `admin_user_roles` is unrepresentable.
- A `requires(permission)` route dependency, and an unknown permission string raising at **import
  time** rather than at request time, so a typo is a failed start rather than a silent denial. Doc
  12:629 requires unknown permissions to fail closed; failing at startup is the strongest form.
- `GET /api/v1/roles` and `GET /api/v1/permissions` behind `role.read`
  (`05_API_Specification.md:873-874`).
- The permission-declaration gate: **every** route under `/api/v1` either declares a permission or
  appears in an explicit, commented allowlist (health, metadata, login, register). A new protected
  route with no declaration fails the build instead of being open.

### What proves it

- `SEC-PERM-001` — a role's permissions come from the seeded catalogue; a permission not granted is
  denied with `PERMISSION_DENIED` (`14_Testing_QA_Acceptance.md:844`).
- `SEC-PERM-002` — a revoked role grant (`revoked_at` set) stops granting immediately.
- `SEC-PERM-003` — an unknown permission string fails at import, proven by importing a module that
  declares one and asserting the failure.
- `SEC-PERM-004` — every `/api/v1` route declares a permission or is on the allowlist, and the
  allowlist is exhaustive rather than a prefix rule.
- `SEC-PERM-005` — no seeded role holds `break_glass.activate` and no route declares it (POL-005).
- `SEC-PERM-006` — `technical_admin` holds none of the financial permissions
  `12_Security_RBAC_Audit.md:664-672` lists, asserted against the seeded matrix.
- `SEC-PERM-007` — a trader identity cannot be granted an internal role: the insert is refused.
- `SEC-PERM-008` — no seeded role is omnipotent; no role holds every permission
  (`15_Agent_Implementation_Plan.md:633`).

### Negative controls

Remove a route's declaration and confirm `SEC-PERM-004` names it. Grant `technical_admin` a
financial permission in the seed and confirm `SEC-PERM-006` fails. Add `break_glass.activate` to a
role and confirm `SEC-PERM-005` fails.

## Slice 6 — Ownership guards and trader isolation

### Goal

`15_Agent_Implementation_Plan.md:613` — "trader ownership guards" — and the seven mandatory IDOR
cases in `14_Testing_QA_Acceptance.md:1274-1284`.

### What it changes

- Ownership derives from `ActorContext.trader_id`, which comes from the session's
  `trader_user_id → trader_users.trader_id`. A `trader_id` in a request path, query or body is never
  used to select scope — the QA case at `:1280` is that exact attack.
- A repository-level scope helper so an own-resource query cannot be written without the trader
  predicate, rather than a reviewer remembering to add a `WHERE`.
- The disclosure policy: for a resource that exists but is not the caller's, the response is the same
  as for one that does not exist (`:1284`), so a 404/403 difference is not an existence oracle.
- `GET /me/trader/profile`, `PATCH /me/trader/profile` with `If-Match`
  (`05_API_Specification.md:918-919`). `:925` requires phone/login changes to use a controlled
  identity workflow, so the patch allowlist excludes them.

### What proves it

- `SEC-IDOR-001` — trader A cannot read trader B's profile.
- `SEC-IDOR-002` — trader A submitting B's `trader_id` in a body is scoped to A, not to B, and the
  attempt is recorded.
- `SEC-IDOR-003` — a trader reaching an admin endpoint is rejected by audience before any permission
  or ownership evaluation, so the order cannot leak that the endpoint exists.
- `SEC-IDOR-004` — an admin response for one trader contains no other trader's data
  (`:1282`), asserted by serializing and searching for the other trader's identifiers.
- `SEC-IDOR-005` — the not-mine and not-existing responses are byte-identical.
- `SVC-SCOPE-001` — the structural half: no repository method returning a trader-owned row is
  reachable without the scope predicate.
- `API-PROFILE-001` — `PATCH /me/trader/profile` without `If-Match` returns
  `PRECONDITION_REQUIRED`; with a stale one, `VERSION_CONFLICT`
  (`14_Testing_QA_Acceptance.md:840-841`).
- `API-PROFILE-002` — the patch cannot change the phone number or any status field.

### Negative controls

Read `trader_id` from the request body and confirm `SEC-IDOR-002` fails. Return 403 for not-mine and
404 for not-existing and confirm `SEC-IDOR-005` fails. Add an unscoped repository method and confirm
`SVC-SCOPE-001` names it.

## Slice 7 — Recent-auth and the separation-of-duties policy service

### Goal

`15_Agent_Implementation_Plan.md:616-617` — the recent-auth abstraction and the SoD policy service —
discharging DOC-CONFLICT-019's M3 evidence.

### What it changes

- `POST /api/v1/auth/reauthenticate` (`05_API_Specification.md:819-841`) taking a password and a
  `purpose`, returning an opaque reference and an expiry. The reference is a hashed lookup, never
  the stored value.
- The context is bound to actor, active session, action/purpose and resource per
  `FINANCIAL_INTEGRITY_BASELINE.md` §3, and consumption is recorded **inside the command
  transaction**, so a timeout-and-retry or an idempotency replay cannot spend one step-up on two
  effects.
- `app/security/step_up.py` with a factor registry holding one entry, `password`. ADR-009 chooses
  what else joins it; the interface is the thing M3 owes.
- `app/security/separation_of_duties.py`: `finalizer_actor_id != approver_actor_id` as a policy
  object with no configuration switch (`FINANCIAL_INTEGRITY_BASELINE.md` §5, DOC-CONFLICT-021
  Approved). M3 has no batch to approve; what M3 owes is the service and its tests, so M6 and M7
  consume rather than re-derive it.
- `RECENT_AUTH_REQUIRED` as a stable error code (`14_Testing_QA_Acceptance.md:845`).

### What proves it

- `SEC-STEP-001` — a critical action without a recent-auth reference returns
  `RECENT_AUTH_REQUIRED`; with a valid one it proceeds.
- `SEC-STEP-002` — a context issued for purpose X is refused for purpose Y
  (`12_Security_RBAC_Audit.md:556`).
- `SEC-STEP-003` — a context issued in session A is refused in session B, even for the same actor
  and purpose.
- `SEC-STEP-004` — an expired context is refused, evaluated server-side.
- `SEC-STEP-005` — a consumed context is refused a second time, and consumption rolls back with the
  business transaction so a failed command does not spend it.
- `SEC-STEP-006` — reauthentication alone approves nothing: it changes no business state
  (`:550`).
- `SEC-SOD-001` — the same identity finalizing and approving is refused, with no configuration that
  permits it — asserted by showing no setting changes the outcome.
- `SEC-SOD-002` — a `system_worker` actor cannot execute a human financial command
  (`14_Testing_QA_Acceptance.md:1294`).
- `AUD-STEP-001` — the audit row links the recent-auth context without recording its secret
  reference in plaintext (`12_Security_RBAC_Audit.md:536`).

### Negative controls

Record consumption outside the command transaction and confirm `SEC-STEP-005` fails after a rolled-back
command. Drop the purpose comparison and confirm `SEC-STEP-002` fails. Add a settings flag that
disables the SoD check and confirm `SEC-SOD-001` fails.

## Slice 8 — Trader registration and approval, admin users, password change and reset

### Goal

`15_Agent_Implementation_Plan.md:608-610` — registration, pending-approval access, and the
reset/recovery process — plus the admin and RBAC management endpoints
(`05_API_Specification.md:867-876`).

### What it changes

- `POST /api/v1/traders/register`, public and rate-limited (`:890`), creating a `traders` row in
  `pending_approval` and its primary `trader_users` row in one transaction, with audit and outbox.
  The first code path that depends on slice 1's defect fixes.
- The pending-account experience: a `pending_approval` trader signs in and reaches only that surface
  (`12_Security_RBAC_Audit.md:431`), enforced by the business axis, not by the account axis.
- `POST /traders/{id}/approve | reject | suspend | reactivate` with `If-Match` and idempotency
  (`05_API_Specification.md:893-896`), on canonical permissions `trader.approve`, `trader.reject`,
  `trader.suspend`, `trader.reactivate` (`permission_catalog.yaml:316-325`) — the canonical spellings,
  which differ from doc 05's for reject and reactivate (`:841-850`).
- `/admin-users` list/create/get/patch/suspend/reactivate on canonical `user.*` permissions, with
  doc 05's `admin_user.*` recorded as aliases (`permission_catalog.yaml:758-763`).
- `POST /auth/change-password` revoking other sessions via a security-stamp bump (`:849`).
- `POST /admin-users/{admin_user_id}/password-reset` (`:854`) setting `recovery_required` and never
  revealing the existing password (`:857`).
- `PUT /roles/{id}/permissions` requiring recent auth for high-risk grants
  (`12_Security_RBAC_Audit.md:637`) and writing a before/after audit (`:639`).

### What proves it

- `API-REG-001` — registration creates trader and primary contact atomically; a failure leaves
  neither.
- `API-REG-002` — **two** registrations succeed, each with its own primary contact. The
  end-to-end form of `DB-PRIMARY-001`, and the test that would have caught defect 2 from the outside.
- `API-REG-003` — registration is rate-limited and does not disclose whether a phone number is
  already registered.
- `API-PENDING-001` — a pending trader can reach the pending surface and nothing else.
- `API-APPROVE-001` — approval is idempotent under a repeated `Idempotency-Key` and requires
  `If-Match`.

  **Slice 8B found the first half of this sentence to be false, and it is recorded here rather than
  quietly narrowed.** The four decision routes require the header
  (`app/api/v1/traders.py:255-256`) and then **discard it**: `trader_lifecycle.decide` takes no such
  parameter, and no route in that family reads or writes the `idempotency_records` table migration
  `_0004` created for exactly this. The citing test issues **one** request, so its name —
  `test_approval_activates_the_business_and_is_idempotent` — is a claim its body does not make.

  What limits the harm is not idempotency but optimistic concurrency: a naive retry resends the same
  stale `If-Match` and gets 412, so a doubled decision needs a client that refetches
  `record_version` first. The mechanism to fix it already exists and is already used —
  `IdempotencyResolver`, driven by `app/commands/rename_center_profile.py`, with a same-key replay
  test at `tests/integration/test_rename_endpoint.py:205-237`. Retrofitting the four routes onto it
  is **the owner's call to schedule**, recorded as an accepted risk if left: what must not happen is
  the sentence above staying in this plan while the code contradicts it.
- `API-APPROVE-002` — approve/reject/suspend/reactivate each write audit and outbox rows in the
  command transaction (`05_API_Specification.md:878`).
- `API-PWD-001` — a password change revokes the caller's other sessions and keeps the current one.
- `API-PWD-002` — an administrative reset sets `recovery_required` and returns no credential.
- `SEC-ROLECHANGE-001` — a role change without recent auth is refused; with it, the audit records before
  and after.

  **Renamed in slice 8B.** The identifier this obligation used to carry is claimed by
  `M2_IMPLEMENTATION_PLAN.md:516` for something entirely different — a session connected as the app
  runtime role attempting `UPDATE` then `DELETE` on `audit_logs` and receiving a privilege error —
  and that one is cited by a merged test. Because coverage is keyed by exact identifier, M2's
  PostgreSQL privilege test was discharging this recent-auth obligation, and the negative control
  below could not fire no matter what the role-change code did.

  Two plans, one string, and no gate could see it. `test_no_obligation_id_means_two_different_things`
  now can, and it reported two more the moment it existed. It also caught **two failed attempts at
  this very rename**: both replacements were plausible names that turned out to be occupied
  elsewhere in M2, which is precisely the mistake it exists to stop.
- `AUD-ROLE-001` — a grant of manager approval, role management, audit export or retention approval
  emits the alert event `12_Security_RBAC_Audit.md:642` requires.

### Negative controls

Make the registration transaction two commits and confirm `API-REG-001` fails. Remove the recent-auth
requirement from the role change and confirm `SEC-ROLECHANGE-001` fails. Reuse defect 2's index and confirm
`API-REG-002` fails — the control that ties the end-to-end test to the schema fix.

## Slice 8B — The platform can create its first administrator

### Goal

Slice 8 shipped trader registration and the four decisions and left the admin-user half undone. That
was recorded as a label — `PENDING` in the traceability gate named "M3 slice 8B", a slice this plan
never described — and the gap it hid is the one that stops a demo dead.

**A fresh deployment cannot onboard its own first user.** `POST /traders/register` is the platform's
only unauthenticated write, so a trader can self-register; approval needs `trader.approve`;
permissions resolve only through `admin_user_roles`; and **no code anywhere constructed an
`AdminUser` or an `AdminUserRole`.** The only creation path in the repository was raw SQL inside test
fixtures. Registration succeeds, and then nothing can ever happen.

The mechanism is specified and was simply not built: `18_Production_Setup_and_Runbook.md:1094-1105`
§11.8 "Create initial administrators" says "Use a secure management command" and states six
requirements for it. Doc 18 is an authoritative baseline, not advisory prose
(`16_Implementation_Documentation_Index.md:154`).

### What it changes

- `app/cli/create_first_admin.py` — one account, one role grant, one audit row, one transaction.
  **Under `app/`, not `services/backend/scripts/`**, because the backend image copies only `.venv`,
  `app/`, `alembic/`, `alembic.ini` and `pyproject.toml` (`infra/docker/backend.Dockerfile:29-32`): a
  command written in `scripts/` would pass its tests, merge, and then not exist in any deployment.
- The password is read from a terminal or stdin, never from `argv` — an argument is visible in the
  process table, in shell history, and in `docker inspect` for the container's lifetime.
- The role is a **required** argument rather than a defaulted one, and is refused unless the seeded
  grant actually includes `user.create`. Which authority the installer carries is a decision about
  who installs the system versus who runs the business, and a default would make it silently.
- Two identifier collisions broken, and the traceability gate's own understated check repaired.

### What proves it

- `SEED-ACCT-002` — the command creates the account, its grant and its audit row together against a
  real database; the audit row is attributed to `system_maintenance` with no actor id because there
  is no human to name; the resulting account can approve a trader and add a colleague and **cannot**
  approve a payment batch version (`18_Production_Setup_and_Runbook.md:1105`); it refuses once any
  staff account exists; it refuses a role that could not add a second administrator; and nothing it
  prints contains the password (`:1099`).

### What it deliberately does not do

`18_Production_Setup_and_Runbook.md:1103` requires the account to "require credential change or
secure activation". **This slice does not meet that, and says so on stderr when it runs.** Setting
`status='recovery_required'` to satisfy the letter of it would be worse than admitting the gap:
`recovery_required` refuses authentication (`app/security/account_state.py`),
`AccountAction.RECOVER` is passed by no application code, and there is no change-password route — so
the flag would produce a correctly-provisioned account that can never sign in and cannot be
recovered. Slice 8C owes the route; until then the install-time password stays in force.

### Negative controls

Delete the "no staff exists" guard and confirm the refusal test fails. The second invocation uses a
**different** username on purpose: with the same one the refusal could come from
`admin_users.username`'s unique index, and the control would pass with the guard gone.

Grant a role holding no `user.create` and confirm the positive test's negative half fails on
`payment_batch_version.approve`. Print the password and confirm the output test fails — which needs
its positive half, or "the password is absent" is satisfied by a command that printed nothing.

## Slice 8C — Changing your own password, and the first security-stamp increment

### Goal

Close the gap slice 8B admitted: the bootstrapped account's install-time password could not be
rotated through any interface. And with it, write the first code in this repository that makes a
security stamp move.

**Narrowed from the original 8C, which also owned the administrative reset and a recovery path.**
Both moved to 8D, and the reason is better factoring rather than schedule: the reset lives at
`POST /admin-users/{id}/password-reset`, so it belongs with the `/admin-users` family that 8D builds,
and the recovery path exists only because the reset creates a `recovery_required` account. Splitting
them here would have put one route of a family in one slice and five in another.

### What it changes

- `POST /auth/change-password`, for both audiences, using the already-registered
  `CHANGE_OWN_PASSWORD` command name.
- The first `security_stamp_version` increment. What the plan's own phrasing for API-PWD-001 cannot
  mean literally: `classify_stamp` compares for **equality** and treats a session ahead of its
  identity as a distinct rejection, deliberately, so one increment invalidates *every* session
  including the caller's. Keeping the current one is a second write — the caller's own session row
  carried forward — not a subtlety of the first.
- Classified **ownership-scoped** in the DoD gate, not `session-only`. That class carries no
  obligation, and naming it that would have been the third time the DoD's first clause was
  discharged for a route by a label.

### What proves it

- `API-PWD-001` — a password change revokes the caller's **other** sessions and keeps the current
  one. The floor: the caller has **at least two** live sessions before, the other answered 200
  before and 401 after, the identity's stamp moved by exactly one, the revoked row carries
  `password_changed` as its reason, the old credential no longer signs in and the new one does. The
  keep-assertion is an *unsafe* request, because the CSRF token is an HMAC over the session's stored
  digest — which the change does not touch — so a safe request would prove the session
  authenticates while saying nothing about whether it can still act.
- `SEC-STAMP-002` — the renamed obligation, which can first fail here because this is the first
  producer.

### Negative controls

Delete the increment and confirm the stamp assertion fails — before this slice it failed nothing.
Delete the bulk revoke and confirm the other session still authenticates. Invert the "not my
session" condition and confirm the caller is signed out by their own change. Remove the line that
carries the caller's session forward and confirm the unsafe request afterwards returns 401 — that
one is the whole reason this is a command rather than an `UPDATE`.

## Slice 8D — Staff account administration: list, create, read, amend

### Goal

The first four routes of the `/admin-users` family, and the first command in this
repository other than `rename-center-profile` that actually **uses** the idempotency
record it requires.

**Narrowed from the original 8D**, which also owned suspend, reactivate, role management,
the reset and the alert. Those move to 8E. The split is along a real seam rather than a
convenient one: these four are CRUD over an identity, while the rest are state
transitions and authority changes that each need a guard this slice does not have — the
rule that the last account holding `user.*` cannot be deactivated, a recovery path, and
the phrase-to-permission mapping behind the alert.

### What it changes

- `GET /admin-users`, `POST /admin-users`, `GET /admin-users/{id}`, `PATCH
  /admin-users/{id}`, each on the **canonical** permission rather than the one doc 05
  declares. `admin_user.read` and `admin_user.manage` are recorded in the approved
  catalogue as deprecated aliases, the second `deprecated_ambiguous` with the instruction
  to select the action-specific canonical permission per endpoint. So the four routes take
  `user.read`, `user.create`, `user.read` and `user.update`, and the mapping is written
  into the catalogue's `endpoint_permission_discrepancies` — four rows, following the two
  trader precedents — so the substitution is reviewable rather than decided inside a route
  decorator. `declare("admin_user.manage")` would raise, which is the fail-closed design
  working: an alias is not a grantable row.
- Splitting one declared permission three ways is not a preference. Doc 12:700 states that
  implementations "may add narrower permissions but must not merge unrelated high-risk
  actions into one broad permission", and one permission covering all three would mean an
  operator who may correct a colleague's phone number may also remove their access.
- `POST` claims and completes an idempotency record through `IdempotencyResolver`. Doc 12
  §12 requires both steps and the four trader decision routes do neither — they require
  the header and discard it, recorded in §3.5 above. The password is deliberately **not**
  in the claim payload: the resolver hashes it to detect a same-key-different-body retry,
  and a credential inside that hash would be a credential in a durable table.
- `PATCH` accepts contact details only. Username, status, credential and role grants each
  belong to their own command, and `extra="forbid"` makes an attempt a 422 rather than a
  silently ignored key — an ignored key is worse, because the caller believes it worked.

### What proves it

- `API-ADMIN-001` — a caller holding none of the four canonical permissions is refused on
  every route, on a request that is otherwise entirely valid, and the refusal is
  attributable to the permission rather than to CSRF. Paired with a privileged caller
  succeeding, because "returns 403" is equally satisfied by a route that refuses everybody.
- `API-ADMIN-002` — a repeated `Idempotency-Key` returns the **first** account rather than
  creating a second person with the same name, an `idempotency_records` row exists for the
  operation, and the same key with a different body is refused with 409.
- `API-ADMIN-003` — no response carries the stored credential or the lockout counters,
  asserted by reading the hash from the database and searching for it verbatim in the
  serialised body rather than by checking field names the test would have to guess right.

### Negative controls

Delete each `requires(...)` in turn and confirm the matching denial case flips to 200 —
which only works because every request in the parametrisation is otherwise valid; omit the
`If-Match` and the mutant answers 428, and the control cannot tell a missing guard from a
present one.

Remove a case from the denial parametrisation and confirm the guard fails: the DoD gate
names **one** test for all four routes, so a parametrised negative that quietly lost a case
would leave a route reported covered by something that no longer runs. The expected set is
derived from the committed OpenAPI contract rather than written beside the parametrisation,
because a hand-written twin can be edited in the same commit. *The first version of that
derivation matched nothing — it stripped the `/api/v1` prefix from the wrong side — and the
non-vacuity floor is what caught it rather than two empty sets comparing equal.*

Skip the `resolver.complete` call and confirm the replay assertion fails rather than the
creation silently succeeding twice.

## Slice 8E — State transitions, role management, and the high-risk-grant alert

### Goal

The rest of the `/admin-users` family and `PUT /roles/{id}/permissions`, plus the alert doc
12:642 requires.

### What it changes

- `/admin-users` suspend and reactivate. The other four shipped in 8D. **Not on doc 05's declared
  permissions:** `admin_user.read` and `admin_user.manage` are recorded in the approved catalogue as
  deprecated aliases, the second `deprecated_ambiguous` with `resolution: select the action-specific
  canonical permission per endpoint`. The canonical four — `user.read`, `user.create`, `user.update`,
  `user.deactivate` — are seeded and held by `business_admin` alone, so both halves of every
  permission test are writable. Using one broad permission would also violate doc 12:700 directly.
- `PUT /roles/{id}/permissions` with the recent-auth consumer, which is build-then-prove rather than
  prove-only: `step_up.rejection_for` has **zero** production call sites today. The header must be
  `X-Recent-Auth`, the name the shipped client already sends.
- The phrase-to-permission mapping behind AUD-ROLE-001, as one derived artifact.
- `POST /admin-users/{id}/password-reset`, moved here from 8C because it is one route of this family
  and belongs with the other five, using the already-registered `RESET_ADMIN_PASSWORD` name. Two
  refusals it must carry, neither of them obvious: **self-reset**, because self plus
  `recovery_required` plus no recovery route is a permanent self-lockout; and resetting or suspending
  the **last** account holding `user.*`, because `business_admin` is the only role holding those and
  nothing today stops one administrator stranding the deployment.
- A recovery path, so `recovery_required` stops being terminal. It arrives with the reset that
  creates it, which is why it moved here too — and it is what finally lets slice 8B's deferred
  `18_Production_Setup_and_Runbook.md:1103` requirement be met.

### What proves it

- `SEC-ROLECHANGE-001` — the renamed obligation, which can first fail here.
- `API-PWD-002` — an administrative reset returns no credential and the target's sessions carry
  `revoked_at` **and** a reason. Both, because a status-based refusal alone leaves `revoked_at` NULL
  and merely re-proves the account-state check that already exists. The floor: assert the target's
  live session count **before** the reset, or "all sessions revoked" is a statement about the empty
  set. And check for absence of a credential in the headers as well as the body — `"password" not in
  body` is also true of a 500.
- `SEC-ACCT-003` — re-cited here from a test that issues a request, replacing the pure-function call
  that discharges it today in a file whose own docstring says "No database and no Redis server".
- `AUD-ROLE-001` — a grant of manager approval, role management, audit export or retention approval
  writes the alert row. Three of those four permissions are granted to **no** seeded role, so the
  only surface on which all four can be granted is this route's permission-set diff — a design that
  hung the obligation on role *assignment* could never exercise more than two of them. The test must
  say in its name that it proves a row exists and not that anything was delivered.
- `SEC-HIGHRISK-001` — the phrase-to-permission mapping is a human reading English prose, so every
  code in it is checked against `permission_catalog.yaml`, an approved artifact the test did not
  write and cannot edit. A mapping naming a permission the platform does not have would read as
  complete coverage while alerting on nothing, and would be discovered missing at the moment somebody
  wanted it.

### Negative controls

Assert the parametrisation has exactly the four keys the plan states — a loop that silently shrinks
is this test's failure mode. Assert every code in the mapping exists in `permission_catalog.yaml`, an
artifact the test did not write. And assert that granting an **ordinary** permission emits nothing:
without that half the test passes on the generic audit row every command already writes.

### What the slice found, and what it could not build

**Doc 12:642 names five capabilities, not four.** The list above says "manager approval, role
management, audit export or retention approval" and omits break-glass; the document's sentence ends
"…retention approval, **or break-glass capability**". The fifth is handled differently rather than
added to the alert list: `permission_catalog.yaml:289-292` records `break_glass.activate` with
`default_roles: []`, `assignment: disabled_for_phase_1a` and
`availability: disabled_by_approved_POL_005`, and the constraint entry says "no endpoint, grant,
feature flag, runtime activation, or financial bypass". A grant of it is therefore not a high-risk
act to be recorded — it is one the approved policy forbids, so it is **refused**. Alerting while
permitting would be the weaker reading, and the alert would be the only trace of a capability
POL-005 says cannot exist. `test_the_document_still_names_the_five_capabilities` pins the sentence
so a later edit re-opens the derivation instead of silently invalidating it.

**Removing a permission from a role cannot be built while ADR-005 is open.** It means deleting a
`role_permissions` row, and `tests/backend/test_no_deletion_machinery.py` forbids every `delete(...)`
in `app/`, absolutely and with **no allowlist**. Its own docstring anticipates the argument for an
exception — "nobody reviews a pull request looking for the purge job it *added*, because adding one
looks like finishing the feature" — and names a route as the most dangerous place for one, which is
precisely where this would have been. Widening a gate in the first slice that trips it, justified by
the slice that needs it, is the failure that gate exists to prevent.

So `PUT /roles/{id}/permissions` accepts the full set, applies additions, and **refuses a request
that would remove anything**, naming ADR-005 in the message. No deployment is stranded: authority is
withdrawn at the two layers where the schema already models revocation properly —
`admin_user_roles.revoked_at`, which keeps the history a composite key could not, and
`roles.is_enabled`. Removing a permission from a role is the only one of the three that needs a
DELETE, and it is the only one refused. **Owed by the slice that closes ADR-005**, not by this one.

**`GET /roles` and `GET /roles/{id}` nearly shipped with a negative test asserting their opposite.**
The first ledger entry named `test_a_reader_cannot_change_a_role`, which signs in as `manager` — a
role the seed grants `role.read` — so it proves the two reads *succeed*. Two DoD obligations would
have been discharged by a test asserting the reverse of what they claim. The denial now uses
`accountant`, which the catalogue grants neither code, and is parametrised over all three routes with
the parametrisation checked against the published contract.

## Slice D1 — The centre's read surface over the businesses it approves

### Goal

Make approval an operator's task rather than a database task.

**This is a deliberate reordering, recorded here rather than taken quietly.** `GET /traders` is
M5's in the original sequence — `SEC-IDOR-004` has sat pending since slice 6 with the note "needs
an internal list endpoint" — and it is built now because the demonstration path breaks without it.
`POST /traders/register` returns no identifier on purpose: returning one would let a caller tell a
real registration from the no-op a duplicate produces, which is the membership oracle that endpoint
exists to avoid. So until this slice the id of a business awaiting approval was reachable only
through `psql`, and showing the platform to anyone required a detour into its database halfway
through.

Nothing is skipped for the reordering. The slice carries its own obligations, negative tests and
controls, and it **discharges** `SEC-IDOR-004` rather than inheriting it — an early endpoint quietly
carrying somebody else's pending obligation is exactly the drift the traceability gate exists to
stop.

### What it changes

- `GET /traders` and `GET /traders/{trader_id}`, both guarded on `trader.read`. Unpaged, recorded as
  a decision: the population is one centre's counterparties, tens rather than thousands, and the
  list-convention envelope M2 built would be a contract change to introduce here.
- `GET /traders/{trader_id}` publishes an `ETag`, which is what makes the four decision routes usable
  from a screen — an operator reads a business and approves it with the `If-Match` the read handed
  them, so a stale view is refused rather than silently overwriting somebody else's decision.
- The rendering of a trader extracted into one helper. `_decide` built the response inline, and a
  second copy is how a field added for one route silently appears — or fails to appear — in the
  other.

### What proves it

- `API-TRADER-001` — the operator path end to end without touching the database: register,
  list, read, approve with the `If-Match` the read returned, and the list then reflects the
  decision. The last step matters because an operator who cannot see the result of their own action
  will take it twice.
- `SEC-IDOR-004` — a response for one business carries no other business's name, phone number or id,
  asserted by serialising and searching rather than by comparing fields a test would have to name
  correctly. Paired with the positive half, because the search assertions are all satisfied by an
  empty response.

### Negative controls

Remove either guard and confirm the denial test flips to 200. The unprivileged caller is
`technical_admin`, which the seed grants no `trader.*` at all — chosen rather than invented, so the
test proves the seeded catalogue withholds the permission rather than that a fixture did.

Return the whole table from the single-business route and confirm `SEC-IDOR-004` fails. Return an
empty body and confirm it fails too: without the positive half, "the other business is absent" is
satisfied by a response containing nothing.

## Slice D3 — The rehearsal: one command that answers "does the demonstration still work"

### Goal

Turn "can we show this to somebody" from an afternoon into a command.

Slices D1 and D2 made the onboarding path reachable by a person. Nothing proved it stayed
reachable: the suite drives a `TestClient` against a live database, which is not nginx, two
Next.js servers, a container network and a browser holding a `__Host-` cookie. The first time that
whole arrangement was exercised it took three diagnoses, and **none of the three was a defect in
the platform** — which is exactly why they must not have to be rediscovered.

### What it changes

- `infra/scripts/rehearse-demo.sh`: tears the stack down, clears the data directory, brings up a
  fresh deployment, registers a business, runs the bootstrap command, and drives both interfaces
  in Chromium.
- `apps/admin-web/tests/demo/approval-path.spec.ts` with its own Playwright config. Not in the
  default check chain, deliberately: it needs a compose stack the gates do not assume, and a check
  that cannot run is worse than one that is absent, because it teaches people to ignore a red
  result.
- From an **empty database** every time. The bootstrap command refuses once any staff account
  exists — correctly, that is the guard slice 8B was built around — so a rehearsal reusing a
  database could never exercise the step an operator performs on installation day.

### The three host facts it encodes

Each cost a diagnosis, and each is written into the script so it costs nobody a second one.

1. Every `docker compose` invocation must see the same `LOCAL_DATA_ROOT`. Without it compose
   resolves a different bind mount, decides the service configuration changed, and **recreates the
   backend mid-run** — surfacing as a 502 from nginx while the backend's own log shows it shutting
   down with a request in flight.
2. `curl` must bypass the host proxy for loopback. A VPN client exporting
   `http_proxy=127.0.0.1:10808` answers 503 itself and the request never reaches nginx, whose
   access log then stays silent — which reads exactly like a broken stack.
3. The signed-in steps are driven by a **browser, not curl**. The session cookie carries the
   `__Host-` prefix and curl refuses to store a prefixed cookie received over plain HTTP; Chromium
   stores and sends it because it treats `localhost` as a trustworthy origin. That difference is
   measured elsewhere in this milestone rather than assumed here.

### What proves it

- `OPS-DEMO-001` — from an empty database: a business applies, the centre's first administrator is
  created by the bootstrap command, signs in through the real form, sees the application and
  approves it; the business then signs in on its own host and sees the decision; and a browser
  holding only a trader session is refused the centre's list.

### What it deliberately does not prove

It signs in through both real forms and lands on each app's root, which is a static shell today. It
says nothing about role-aware navigation or a session-derived dashboard, and those obligations stay
owned by the slice that will build them. The spec does not name their ids at all — the traceability
scanner counts any obligation id in a test file as coverage, so a sentence explaining that
something is deferred would register as proof that it is done.

## Slice D4 — The way in: a goldsmith can apply without anybody running a command

### Goal

Close the last manual step on the demonstration path.

`POST /traders/register` has existed since slice 8 and nothing in either interface called it.
The rehearsal registered its business with `curl`, and said so in a comment that this slice
deletes: *"there is no registration screen yet, and pretending otherwise in a rehearsal would hide
the one manual step a demonstration still has."* That comment was the honest thing to write and the
wrong thing to keep. A goldsmith is the one person on this
platform who arrives with no account, no invitation and nobody to run a command for them, and until
this slice the only door was an HTTP client.

### What it changes

- `apps/trader-pwa/app/register/page.tsx` and `src/registration.ts`: six fields, Persian,
  right-to-left, against the public route. Per-app rather than shared, on `UI-ISO-001`'s standing
  argument — a path absent from the module graph cannot reach the bundle.
- The trader login footer becomes a link. It has read *"no account? apply to work with us"* since
  slice 9 and pointed nowhere; a prompt to do something the interface offers no way to do reads as
  a broken page rather than a missing feature.
- `packages/config/styles/tokens.css` gains `--danger-50`, `--danger-500` and `--danger-700`.
  `login-form.tsx:85` has styled its failure box with the first two since it was written and none
  of them were ever defined — an undefined custom property is not a build error and not a lint
  error, so `var(--danger-50)` fell back to transparent and the error box has never been red.
- The rehearsal registers **through the form**, so the one step it faked is now the first thing it
  proves.

### The decision this screen turns on

The endpoint answers `{accepted: true, pending_approval: true}` to three different situations: a
real registration, a phone number already registered, and a string that is not an Iranian mobile
number at all (`services/backend/app/api/v1/traders.py:253-256`). The first two are identical **on
purpose** — anything else is a membership oracle for the centre's customer list — and the third is
swallowed under the same reasoning.

Two consequences follow, and they pull in opposite directions.

The screen cannot say an account was created, because it does not know. Whatever it says has to be
true of a duplicate too, which rules out every natural phrasing of success and leaves one that is
better anyway: *sign in with the number you entered to see where you stand*. That lands the reader
on `/profile`, which is where the status actually lives, rather than on a claim.

And the phone number has to be checked **here**, because the server has decided not to. Without it
a mistyped number produces a confident "you are in the queue" for an application that was never
written, and the person waits for a decision on nothing. This is safe to do on the client precisely
because it is not the secret: the shape of a phone number is computable offline by anybody, while
membership stays the server's to refuse. The rule is a mirror of
`app/security/identifiers.py:80-109` and is **not a control** — if the two ever disagree the server
wins. The drift is asymmetric and the client is written to accept when in doubt: a client stricter
than the server locks somebody out of their own registration, a client looser only returns to
today's behaviour.

No password policy is invented. `app/security/passwords.py:25` records that the platform
deliberately has no minimum length, no composition rules and no strength meter; a form adding its
own would be making that decision in the one place nobody would look for it, and enforcing it only
on the people who arrive through the form. The confirmation field is not a policy — it catches a
typo in a value the person cannot see and would otherwise meet at their first login.

### What proves it

- `UI-REG-001` — the client's phone rule accepts every spelling of one number that the server
  accepts, including Persian and Arabic-Indic digits and the invisible marks pasted text carries,
  and refuses a landline, a foreign number and the wrong lengths. The cases are lifted from the
  server module's own docstring rather than invented, so a change to the server's rule is what
  fails them. Paired with the assertion that the request sends the number **as typed**: the
  server's normalisation is what decides which row `UNIQUE (phone_number)` collides with, and
  sending our folded form would make this bundle's copy part of the identity — a drift would then
  open a second account for one person instead of being corrected.
- `UI-REG-002` — the success wording asserts nothing the screen cannot know. Checked against the
  message table, negatively against four phrasings that claim an account now exists, and positively
  against the sentence pointing the reader at their profile — because "does not contain four
  phrases" is also satisfied by a message that says nothing.

### Negative controls

Make the client's phone rule reject Persian digits and confirm `UI-REG-001` fails — the case that
matters most in the deployment country and the one an ASCII-only rule silently loses. Change the
success message to announce a new account and confirm `UI-REG-002` fails. Delete the
`trader.register.done` key and confirm the guard-the-guard fails **first**: every assertion in that
group reads a string out of `messages.ts` by pattern, and a key that stopped matching would yield
the empty string, which claims nothing and passes everything.

## Slice 9 — The two frontends: login, role-aware navigation, and audience isolation

### Goal

`15_Agent_Implementation_Plan.md:614` — role-aware navigation — and the DoD's second half. **This is
the slice where the interface becomes visible.**

### What it changes

- Admin Web login and Trader PWA login: Persian, right-to-left, against the two routes from slice 4.
- Six of the mandatory application states, as shared components, because every later screen needs
  them and inventing them per screen guarantees six variants: loading, forbidden, stale,
  missing-precondition, idempotency and timeout.

  **Corrected in slice 10B: this list is a subset, and the sentence it replaced said otherwise.**
  `21_UI_Design_System_and_Screen_Specification.md:688-705` requires **eighteen** states of every
  screen, not six, and the six above are the ones with a normative subsection minus two. The plan
  originally read "the mandatory application states `…:684-767` requires — loading, forbidden, …",
  which asserted that the document required those six. It does not. The citation gate could not
  catch it: `tests/backend/test_plan_citations.py:13-19` states its own limit, that it proves a cited
  line exists and not that the line says what the sentence claims — and this is the first case of
  that limit biting in practice rather than in principle.

  The twelve the document requires and no slice builds are recorded in slice 10C below, because a
  subset presented as a whole is how a UI ships without its refusal states.
- Role-aware navigation from `GET /auth/me`'s permission list, used **for UX only**: the backend is
  authoritative (`12_Security_RBAC_Audit.md:625-626`), so a hidden item is not a control and a shown
  one is not a grant.
- No credential in `localStorage` or `sessionStorage` (ADR-001, `12_Security_RBAC_Audit.md:373`).
- Separate bundles with no shared authenticated client, so an admin call is not reachable from the
  trader bundle's code at all.

### What proves it

- `UI-LOGIN-001` — each app signs in against its own route and lands on its own dashboard.
- `UI-LOGIN-002` — an invalid credential shows the generic message and no account-existence hint.
- `UI-ISO-001` — the trader bundle contains no admin endpoint path and no admin client, asserted
  against the built output rather than the source.
- `UI-ISO-002` — a trader session cannot reach an admin surface end-to-end in a real browser: the
  DoD's second half, and the reason slice 4's cookie is host-only under the `__Host-` prefix.
- `UI-STORE-001` — after login, no storage key holds a session secret or a token.
- `UI-STATE-001` — each mandatory application state renders from a real server response, not from a
  hand-set prop.
- `UI-NAV-001` — navigation reflects permissions, and a hidden action still fails server-side when
  called directly. Proves the frontend is not the control.

### Negative controls

Import the admin client into the trader bundle and confirm `UI-ISO-001` fails. Write the session id
to `localStorage` and confirm `UI-STORE-001` fails.

The control this slice originally listed — "widen the cookie path to `/` and confirm `UI-ISO-002`
fails" — **cannot fail** and was replaced. Browsers key cookies by host before path, so a host-only
cookie on `admin.localhost` is never sent to `trader.localhost` no matter what `Path` says; the
control would have reported success while testing nothing.

**The replacement cannot fail either, and slice 10B has now measured it rather than argued it.** The
replacement was to set `Domain` on the cookie "which makes it sibling-visible", and require
`UI-ISO-002` to fail. Run in Chromium against a server on `http://localhost` — where
`Domain=localhost` *matches* the host, so a mismatch cannot be the cause — the result is:

```text
STORED    __Host-correct=1; Secure; Path=/
REJECTED  __Host-with-domain=1; Secure; Path=/; Domain=localhost
REJECTED  __Host-no-secure=1; Path=/
REJECTED  __Host-narrow-path=1; Secure; Path=/somewhere
STORED    ordinary-with-domain=1; Path=/; Domain=localhost
```

A `__Host-` cookie carrying `Domain` is **refused outright**, so the trader would hold no session at
all: `admin.localhost` then refuses them for being anonymous rather than for being a trader, and the
control reports that isolation works while proving nothing about it. The last line is the control
inside the control — an ordinary cookie with the same `Domain` *is* stored, so the refusal is caused
by the prefix and not by an invalid attribute or an unreachable server.

That is the **second** proposed control for this one cookie to turn out inert, which is the finding
worth carrying forward: a negative control aimed at a mechanism the browser enforces will usually be
refused by the browser instead of weakening the mechanism. The control that does bite asserts the
refusal itself — that Chromium rejected the `Domain`-bearing cookie and the jar is unchanged — and it
is now a kept test rather than a manual step (`UI-ISO-003`).

Note also that native dev serves both apps on `localhost` at different ports and cookies ignore
ports, so any *end-to-end* isolation test still has to run against the compose stack's distinct
hostnames. One fact makes that affordable and was also measured: `isSecureContext` is **true** on
plain-HTTP `localhost`, so the unconditional `secure=True` at `app/api/v1/auth.py:252` does not
require TLS in the local stack. Reaching for a Chromium flag such as
`--unsafely-treat-insecure-origin-as-secure` would have tested a different system from the one that
ships.

## Slice 10 — The Definition-of-Done gate and M3 evidence

### Goal

Make the DoD a gate rather than a claim, and record what M3 cannot prove.

### What it changes

- `tests/security/test_m3_definition_of_done.py`: enumerate every protected resource from the
  router, and for each require **both** a negative ownership test and a negative permission test.
  A protected route with neither fails the gate and names itself. The obligation list is derived
  from the router, not written beside it, because a hand-written list of protected resources is the
  fifth copy of a thing that drifts.
- The seven mandatory IDOR cases (`14_Testing_QA_Acceptance.md:1274-1282`) mapped to their tests,
  with the cases whose resources do not exist until M4/M5 recorded as deferred **with the milestone
  that owns them** rather than silently absent.
- The six SoD cases (`:1288-1295`) and the ten session/recent-auth cases (`:1299-1310`) mapped the
  same way.
- `scripts/emit_evidence.py` extended with M3's items, reading state from the running instance as
  slice 10C established, and recording the ADR-009 factor decision as unfilled with the section 2.5
  reason.

### What proves it

- `TRACE-DOD-001` — the gate discovers protected resources from the router; adding a protected route
  with no negative tests fails it.
- `TRACE-DOD-002` — every deferred QA case names the milestone that owns it; a deferral with no owner
  fails.
- `TRACE-QA-001` — each mandatory QA case from doc 14 §16 maps to a test or a recorded deferral, and
  the mapping is keyed by explicit case ID so renumbering cannot hide an omission — the lesson from
  M2 slice 10B.
- `OPS-EVID-001` — the evidence artifact records M3's state and refuses to write when the instance is
  unreachable.

### Negative controls

Add a protected route with no negative tests and confirm `TRACE-DOD-001` names it. Remove a
deferral's milestone and confirm `TRACE-DOD-002` fails. Renumber a QA case and confirm
`TRACE-QA-001` fails.

## Slice 10B — The stack can authenticate, and the DoD's first clause becomes tests

### Goal

Close the two things slice 10 recorded as owed and one it did not know about. Slice 10 left six
obligations pending against a slice this plan did not describe, which is its own small version of
the failure it was written to prevent: an owner with no section is an owner nobody can review.

**The one it did not know about is a live defect, not a gap.** The compose stack answered **500 to
every correct password** and 401 to every wrong one. `AUTH_CSRF_KEY_SECRET` reached `.env.example` in
slice 4 and reached the backend container never, so `cookies.csrf_token` raised on an empty HMAC key
on the *success* path — the path no smoke check visits, because they all probe with a bad credential.
It was invisible from two directions at once: the wrong-password probe returns the same 401 either
way, and every integration settings factory passes the secret in directly
(`tests/integration/test_authentication_flow.py:74`), so 514 green integration tests and a stack
nobody could log into were entirely consistent with each other.

Production was never exposed — `app_env=production` refuses to start without the secret — which
means the broken window was exactly `local` and `ci`. That is to say: every demo.

### What it changes

- `infra/compose/compose.local.yml` forwards the two optional auth secrets, in the `${VAR:?}` form so
  an absent value stops the stack rather than starting it with a known key.
- The CI `.env` generator **derives** its list of placeholders from `.env.example` instead of
  restating it, and refuses to write a file in which any placeholder survived. The hand-written list
  had left four secrets — both `AUTH_*` keys and two database roles — at the example's published
  text: present, so `${VAR:?}` was satisfied, and readable by anyone with the repository.
- A login smoke stage in **both** verifier languages, asserting that a *correct* credential completes
  and sets `__Host-gp_trader_session`.
- The three permission-denial tests slice 10 owed, the two positives that had never existed — nothing
  in the repository had ever driven suspend or reactivate to 200 — and a discriminator that separates
  a permission refusal from a CSRF refusal, since `CsrfRequiredError` and `ForbiddenError` are
  byte-identical by design.
- `GET /auth/sessions` and `POST /auth/sessions/{id}/revoke` reclassified from `session-only` to
  ownership-scoped. Slice 10 put them in the one class carrying no obligation, so the DoD's first
  clause was discharged for them by a label.
- The browser contract the whole cookie design delegates to the client, as a kept test.

### What proves it

- `OPS-ENV-001` — every optional secret `config.py` declares is forwarded to the backend container,
  derived from the source rather than listed beside it, and forwarded as required rather than
  defaulted.
- `OPS-ENV-002` — every placeholder `.env.example` ships is replaced by CI, and anything *named* like
  a credential ships spoiled, which closes the case a new placeholder spelling would open.
- `SEC-PERM-003` — reject, suspend and reactivate each refuse an authenticated caller without the
  grant, on a request that would otherwise have succeeded, and the refusal is attributable to the
  permission rather than to CSRF.
- `SEC-IDOR-005` — one admin's session list does not contain another admin's session.
- `SEC-IDOR-006` — one admin cannot revoke another admin's session, the refusal is indistinguishable
  from a fabricated id, and the victim's session still authenticates afterwards.
- `UI-ISO-003` — Chromium enforces every part of the `__Host-` contract the deployment relies on:
  a `Domain`-bearing prefixed cookie is refused, an insecure one is refused, a path-narrowed one is
  refused, and plain-HTTP `localhost` is a secure context so the shipped `secure=True` needs no TLS
  locally.

### Negative controls

Remove each of the three `requires(declare(...))` guards in turn and confirm the matching denial test
flips from 403 to 200 — which only works because each request is otherwise valid; omit the `If-Match`
and the mutant answers 428, and the control cannot tell a missing guard from a present one.

Make `csrf_token_matches` always return `False` and confirm **every** permission test fails. Without
the logout probe they all pass: the status is 403 and the code is `FORBIDDEN` either way, so the
suite would have been asserting a CSRF refusal and calling it a permission check.

Stop forwarding the CSRF secret and confirm `OPS-ENV-001` names it; forward it with a default instead
of `:?` and confirm the same gate refuses that too. Blind the config parser and confirm the canary
fires rather than the file passing over an empty set.

Make the cookie server send no `Set-Cookie` at all and confirm `UI-ISO-003` fails: every "must be
refused" expectation is satisfied by a browser that received nothing, and the two positive
assertions are what give the refusals meaning.

## Slice 10C — The application states, the evidence artifact, and the twelve missing states

### Goal

What slice 10B deliberately did not claim, recorded here so the deferral has a section rather than a
dictionary entry.

### What it changes

- An `ApiError` → state mapping, which exists nowhere today: no code in either frontend turns a
  status or an error code into a state, so there is nothing for a real response to drive. It cannot
  live in `packages/ui`, which has no dependency on the API client.
- The three of the plan's six states that have no component, no kind and no Persian message:
  missing-precondition, idempotency conflict, and timeout.
- The **twelve** states `21_UI_Design_System_and_Screen_Specification.md:688-705` requires that no
  slice has ever named: partial loading, empty state, not found, validation error, workflow
  rejection, background processing, processing failure, file quarantined, export integrity mismatch,
  maintenance/read-only mode, session expired, recent-auth required. Each either mapped or recorded
  as owed, with the milestone that owns it — several describe files, exports and background jobs that
  do not exist before M6.
- The evidence emitter's M3 items, and a decision about the identifier: the plan says `OPS-EVID-001`
  and the tests say `OPS-EVIDENCE-001`, which is M2's. Coverage is keyed by exact id, so the M3
  obligation has **zero** citations today and adding it to an existing docstring would be the
  cheapest possible false discharge.

### What proves it

- `UI-STATE-001` — each state renders from a recorded real server envelope, and the fixture is
  asserted byte-equal to what the running server returns, so the recording cannot drift into a
  hand-typed stub. The floor is parsed from the document's eighteen bullets rather than iterated from
  the component's `StateKind`, which would derive the floor from the thing under test and report
  green over five of eighteen.

### Negative controls

Delete the fixture and confirm the frontend test **fails rather than skips**. Rename an error code
inside the fixture and confirm the Python test fails — that is the assertion binding the two layers,
and without it the fixture is a hand-written stub with extra steps.

### What the slice found

**The plan said twelve states were missing; eleven were.** Its list includes "empty state", which
`StateKind` has carried since slice 9. The error is invisible from inside the plan and obvious from
the document, which is why `packages/api-client/test/application-state.test.ts` parses the floor out
of `21_UI_Design_System_and_Screen_Specification.md` §7 rather than restating it. Eighteen
documented, four that existed, fourteen added.

**`OPS-EVID-001` and `OPS-EVIDENCE-001` are two obligations, not one misspelling.** M2's is about the
emitter's shape and its refusals — every field M2 can supply is present, an unreachable instance
produces no artifact, an unsupplyable field is null with its reason. M3's is about the artifact
carrying **M3's own state**. Ruling them the same would have discharged an M3 obligation with an M2
test, and it needed exactly one docstring line. `tests/backend/test_evidence_m3_items.py` is a
separate file for that reason.

**The evidence item an identity milestone would most want is the one it cannot supply.** "Which
permissions does the deployment actually resolve" needs the running instance, and the instance does
not publish it; adding that to `/api/v1/operations/release-evidence` changes a published schema whose
breaking-change waiver process is an unresolved `TODO(governance)`.
`authorization.catalogue_digest` answers a **different** question — what the build was made to grant
— so it is attributed to `repository` in `source_of_each_field`, and the instance's answer is
recorded as unfilled with that reason. Filing the repository's answer under the instance's name is
the same substitution the emitter already refuses for the Alembic revision.

**A guard-the-guard caught the role counter before it could report a fact.** The first
`declared_roles` pattern looked for a `code:` child that roles in `permission_catalog.yaml` do not
have, and counted zero. Nothing about the artifact would have looked wrong: the digest beside it was
correct, and "this release declares 0 roles" would have been filed as evidence that authority is
absent rather than as evidence that a regular expression broke.

**`packages/api-client` could not read a file.** Its only file-reading test was `.mjs`, so the
package had never needed `@types/node`; a `.ts` test importing `node:fs` failed with TypeScript
reporting the module specifier itself as an unknown name. `apps/admin-web` gets those types through
Next's `next-env.d.ts` and has never had to say so. Fixed by naming `types: ["node"]` in the
package's own tsconfig rather than by moving the test somewhere it would compile — the test belongs
beside the mapping it drives.

## Slice 10D — A landing surface, role-aware navigation, and the end-to-end browser run

### Goal

The three frontend obligations that are **build-then-prove**, which slice 9 listed as prove-only.
Recorded as a section for the same reason 10B and 10C are: slice 10 owned six obligations to a slice
this plan did not describe, and an owner with no section is an owner nobody can review.

### What it changes

- A landing surface that differs by session. Today both login handlers do `router.refresh()` then
  `router.replace("/")`, and `/` is a static shell with a hard-coded navigation and a literal
  "role unknown" header — an authenticated admin and an anonymous visitor render identical bytes.
- Navigation that reads permissions. `NavigationItem` is `{href, label}`, both renderers map
  unconditionally, and neither app fetches `GET /auth/me` at runtime: both auth adapters are exported
  and imported nowhere.
- The compose-stack browser run for end-to-end audience isolation, which needs the frontend images
  rebuilt — the ones on disk predate the login screens.

### The owner decision this slice needed first — **resolved**

**Which permission gates each navigation item.** `21_UI_Design_System_and_Screen_Specification.md`
§6.3 gives per-role navigation lists that disagree with migration `_0008`'s seeded grants, and the
obvious mapping is actively wrong: `accountant` — the only unprivileged role that exists — holds
`trader.read`, `audit.read`, `payment_request.read`, `bank_result_bundle.read` and
`bank_profile.read`, which is a read permission behind every admin navigation item. Gating the
traders item on `trader.read` would therefore hide nothing from anybody, and the test asserting it
hides something would have to be written against a permission nobody is granted.

**Decision (owner, slice 10D): gate on the permission that lets you *act*, not the one that lets you
read.** So the traders item is gated on `trader.approve`, work queues on `manual_review.assign`,
payment requests on `payment_request.review`, batches on `payment_batch.create`, bank results on
`bank_result_bundle.upload`, and settings on `source_bank_account.manage`.

The rule is broken exactly once and the exception is recorded in
`apps/admin-web/src/navigation.ts`: there is no "act on the audit trail" permission, because the
trail is append-only and nobody edits it. `audit.export` is the nearest action and **no seeded role
holds it**, so gating on it would hide the item from everyone — which is worse than showing it.
`audit.read` is the honest gate there.

### What the decision turned out to mean

**Gating on actions makes the navigation role-shaped, not role-ranked.** The first version of the
test asserted that an administrator sees more than an accountant, and it failed: `business_admin`
sees four items and `accountant` sees six. Neither is a superset of the other — `accountant` is the
operational role and `business_admin` the administrative one. The design was right and the
assumption was wrong, so `UI-NAV-001` asserts *mutual difference* with each role holding something
the other lacks, which is the honest form of "navigation reflects permissions".

### What proves it

- `UI-LOGIN-001` — each app signs in against its own route and lands on a surface that differs by
  session, asserted against something an anonymous visitor does not render.
- `UI-NAV-001` — navigation reflects permissions, **and** a hidden action still fails server-side when
  called directly. The second half is what proves the frontend is not the control, and it is the half
  that must not be dropped if the first becomes expensive.
- `UI-ISO-002` — a trader session cannot reach an admin surface end-to-end in a real browser, with a
  positive control on the trader's own host so the refusal is proved host-caused rather than
  universal, and with the session cookie's presence in the jar asserted first so the test cannot pass
  because nobody was logged in.

### Negative controls

Point `UI-ISO-002`'s refusal assertion at the trader's own host and require it to fail — a 401 that
also appears on the caller's own origin proves nothing about isolation. Hide a navigation item and
confirm the server still refuses the call it hid: that is `UI-NAV-001`'s second half, and it fails on
a frontend that was made the control.

---

# 3.5 Defects slice 8B found in merged work, and their disposition

Recorded here rather than fixed silently or fixed out of charter. Each was found while planning the
administration endpoints; none is in 8B's scope; all are in shipped slices.

**Suspending a trader does nothing.** `require_operable` (`app/api/v1/trader_self_service.py:90-100`)
tests only `trader.approval_status not in OPERABLE_APPROVAL_STATES`, and that set is
`frozenset({"approved"})`. It never reads `operational_status`. `SUSPEND_TRADER` returns
`{"operational_status": SUSPENDED}` and nothing else, and every other reference to that column in
`app/` is a write, a DTO field, an index or a comment — **none is an authorization read.** So a
suspended business remains `approved`, passes the guard, and can do everything it could before.

The blast radius today is small because the only trader surface is their own profile, and that is
also why it survived: slice 10B wrote the first-ever positive test for suspension and it asserted the
column changed, which is the whole of what suspension does. It will stop being small the moment M4
adds a payment surface on the assumption that suspension means something.

*Disposition: the owner's call, because it is a product question rather than a bug with one right
answer — may a suspended business still read and edit its own profile, or is suspension a full stop?
The code answers "yes it may" by omission, which is the one answer nobody chose.*

**`SEC-ACCT-003` is discharged by a test that cannot fail.** The obligation is stated as endpoint
behaviour — "a `recovery_required` account may call only the recovery endpoint; an otherwise valid
protected request fails" — and its only citation calls `refusal_for(...)` three times with literal
arguments, in a file whose own docstring says "No database and no Redis server". There is no recovery
endpoint, and `AccountAction.RECOVER` is passed by no application code at all. *Disposition: slice 8C
builds the recovery path; the citation must move to a test that issues a request.*

**SEED-ACCT-001 is stricter than the specification, and the divergence was never registered.**
`12_Security_RBAC_Audit.md:386` forbids seeded **development** credentials "in production images or
migrations". `13_DevOps_Deployment_Operations.md:907` explicitly permits initial administrator
creation by "a controlled command **or migration task**". This repository's gate forbids any identity
`INSERT` in any migration — the stricter reading, chosen silently. 8B's command makes the question
moot in practice, so nothing is blocked.

*Disposition: a `CONFLICT_REGISTER.md` row is owed, because a silently chosen reading of a document
conflict is exactly what that register is for. Not added here, because a new conflict changes the
register's severity totals and five sites restate them — a gated governance amendment, not a line to
append at the end of an unrelated slice. Owed to slice 1B, which is already the governance-hygiene
slice.*

---

# 4. Risks this plan accepts, and why

**The frontends arrive at slice 9, not slice 1.** The owner has asked repeatedly when the interface
becomes visible, and putting login screens first would answer that sooner. It would also mean
building them against an authentication contract that slices 4 through 8 are still deciding, then
rewriting them. The cost of the current order is visible progress deferred by eight slices; the cost
of the other order is the login screen written twice and a period where the visible thing does not
enforce the invariants it appears to. Slice 4 does produce a working `curl`-level login, so
authentication is demonstrable well before it is pretty.

**Timeout and factor numbers stay provisional.** Every test asserts a mechanism rather than a
duration, which means a wrong default ships without a test failing. That is the honest position:
ADR-SEC-002 and ADR-009 are open, and a test asserting 15 minutes would be enforcing an unapproved
decision while looking like evidence. The mitigation is that startup validation rejects an absent or
non-fail-closed value, so the number is always deliberate even while it is provisional.

**Slice 1 edits an approved catalogue.** Amending `status_catalog.yaml` needs recorded owner
approval, and until that is recorded slice 1's migration is enforcing a decision at CHECK level. The
mitigation is that it ships in the same pull request as the reasoning, so approval and enforcement
are reviewed together rather than the constraint arriving first.

**Two defects were found by planning, not by the suite.** Both were invisible because the table they
depended on did not exist. The structural gate `DB-SPEC-001` closes the class for doc-specified
constraints, but the deeper lesson is narrower and worth stating: M2 gated the migration against the
model and the model against the tests, and never gated either against the specification. A
constraint the specification states and the code does not is the one shape a
model-versus-migration comparison can never see, because both sides can be wrong together.
