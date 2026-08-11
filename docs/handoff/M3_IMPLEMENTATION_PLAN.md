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
- `SEC-STAMP-001` — bumping the identity's `security_stamp_version` invalidates every live session
  for that identity on the next request. The mechanism behind every revocation trigger in
  `12_Security_RBAC_Audit.md:468-477`.
- `SEC-EVENT-001` — a failed login writes an `auth_events` row; the row contains no credential
  material, proven by asserting the password string is absent from the serialized row.
- `SVC-ACTOR-001` — `app/security/actor.py` imports nothing from `fastapi`, `starlette` or
  `app.api`, so transport-neutrality is structural.

### Negative controls

Store the session secret in place of its hash and confirm `SEC-SESS-001` fails. Skip the
security-stamp comparison and confirm `SEC-STAMP-001` fails. Add the password to the event metadata
and confirm `SEC-EVENT-001` names the field.

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
- `API-APPROVE-002` — approve/reject/suspend/reactivate each write audit and outbox rows in the
  command transaction (`05_API_Specification.md:878`).
- `API-PWD-001` — a password change revokes the caller's other sessions and keeps the current one.
- `API-PWD-002` — an administrative reset sets `recovery_required` and returns no credential.
- `SEC-ROLE-001` — a role change without recent auth is refused; with it, the audit records before
  and after.
- `AUD-ROLE-001` — a grant of manager approval, role management, audit export or retention approval
  emits the alert event `12_Security_RBAC_Audit.md:642` requires.

### Negative controls

Make the registration transaction two commits and confirm `API-REG-001` fails. Remove the recent-auth
requirement from the role change and confirm `SEC-ROLE-001` fails. Reuse defect 2's index and confirm
`API-REG-002` fails — the control that ties the end-to-end test to the schema fix.

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

### The owner decision this slice needs first

**Which permission gates each navigation item.** `21_UI_Design_System_and_Screen_Specification.md`
§6.3 gives per-role navigation lists that disagree with migration `_0008`'s seeded grants, and the
obvious mapping is actively wrong: `accountant` — the only unprivileged role that exists — holds
`trader.read`, `audit.read`, `payment_request.read`, `bank_result_bundle.read` and
`bank_profile.read`, which is a read permission behind every admin navigation item. Gating the
traders item on `trader.read` would therefore hide nothing from anybody, and the test asserting it
hides something would have to be written against a permission nobody is granted.

The only permissions that both discriminate the two seeded roles and guard a route are
`trader.approve/reject/suspend/reactivate`. Whether navigation is gated on the *action* permission
rather than the read one is a product decision, not an implementation detail, and `UI-NAV-001`'s two
halves cannot be made to touch the same grant until it is recorded.

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
