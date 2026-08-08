# M0 Architecture and Policy Decision Index

Status: Working M0 governance register with recorded approvals
Decision state: ADR-001, ADR-006, POL-002 and POL-005 Approved; 29 entries remain Open
Alias mapping: namespace resolved 2026-08-01 (DOC-CONFLICT-003). Every alias now
carries a recorded mapping; no `needs_mapping` entry blocks Phase 1A.
Canonical source: Implementation Docs/00_Start_Here/Open_ADR_Register.md
Approval identity for approved entries: workspace owner approval via conversation; legal name/organizational role not supplied
Owner role/name and due date: TBD for every remaining Open entry

## Registry rules

- The canonical ID is the ID already present in Open_ADR_Register.md.
- Aliases are cross-document references only. They do not replace the canonical ID and do not represent an approved decision.
- proposed_mapping means the wording appears semantically aligned, but an owner must still approve the mapping.
- needs_mapping means the alias is composite, narrower, broader, or overlaps more than one canonical decision.
- An ADR-OPS numeric suffix must not be assumed to match an OPS numeric suffix. Mapping is semantic, not numeric.
- Safe defaults are temporary containment rules. They do not resolve an Open decision.
- AI decisions do not block Phase 1A while all AI/provider features remain disabled.
- Namespace decision, approved 2026-08-01: `Open_ADR_Register` IDs are the only
  canonical namespace. A narrower alias maps to its canonical without satisfying
  it, and a broader alias is split across the canonicals it touches; anything no
  canonical covers is recorded as out of Phase 1A scope. A decision closes only
  when its canonical entry closes, never because an alias was decided.
- The six remaining `ADR-AI-*` aliases against the composite `ADR-OPS-015` are
  parked, not unresolved: splitting a provider/retention/rollout/cost decision
  that nothing may implement would fix wording before the question is real. They
  are resolved at Phase 1B entry, and every one of them stays disabled meanwhile.

## Approved decision inventory

| Canonical ID | Status | Decision | Approval date | Approval evidence | Record |
|---|---|---|---|---|---|
| ADR-006 | Approved | UTC persistence/transport, Gregorian canonical API values, and `Asia/Tehran` business-day/cutoff interpretation | 2026-07-20 | workspace owner approval via conversation; legal name/organizational role not supplied | `ADR-006_Business_Timezone_and_Calendar_Rules.md` |
| POL-005 | Approved for Phase 1A | Break-glass access is disabled; no route, grant, flag, or bypass may weaken mandatory outgoing-batch `finalizer != approver` separation | 2026-07-20 | workspace owner approval via conversation; legal name/organizational role not supplied | `../governance/FINANCIAL_INTEGRITY_BASELINE.md` §5 |
| POL-002 | Approved for Phase 1A | Correcting a published paid result requires manager authority or dual control; the accountant-only default is rejected, the previous publication and its evidence are preserved, and preparer/approver stay split | 2026-08-01 | Ehsan Shams, project owner; approval via the M0 decision session, recorded on their instruction; legal name/organizational role not supplied | `../governance/CONFLICT_REGISTER.md` DOC-CONFLICT-002 |

## Complete decision inventory

| Canonical ID | Decision | Category | Related aliases | Alias state | Safe default while open | Owner role | Owner name | Due date | Blocking milestone or gate | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| ADR-001 | Browser authentication and session transport | Core / Identity | ADR-SEC-001; ADR-SEC-002; ADR-OPS-005 | **Resolved 2026-08-01.** ADR-SEC-001 → ADR-001 for the authentication/session transport half, and → OPS-003 for cookie scope, origins and TLS/HSTS. ADR-SEC-002 is a subset: it decides session timeout only and does not satisfy ADR-001, which still owns the transport choice. ADR-OPS-005 splits the same way as ADR-SEC-001. | **Approved for Phase 1A (2026-08-08): server-side session records carried by a secure, HTTP-only, `SameSite` cookie, with CSRF protection on every unsafe method.** This confirms the preferred browser baseline document 12 section 6.1 already states, rather than taking the bearer-token exception that section permits only with explicit ADR approval. Three reasons decided it. The schema M2 shipped is already a server-side session store: `auth_sessions` holds a secret **hash**, `revoked_at`, `revocation_reason` and `security_stamp_version`, and a stateless token would make immediate revocation require a server-side denylist — a session table under another name, with none of the constraints. Both browser apps sit behind one nginx, so a same-site cookie needs no cross-origin token plumbing. And `no long-lived credential in localStorage` is not a preference here: a stolen browser profile must not yield a reusable financial credential. Domain services stay transport-neutral and consume an `ActorContext`, never JWT claims, so the choice is reversible behind the interface if a later milestone needs it. Cookie **scope, origins and TLS/HSTS** are not decided here — they remain OPS-003. Idle and absolute **timeouts** are not decided here — ADR-SEC-002 owns them and is a subset that does not satisfy this decision. | Approval identity recorded without inferred organizational role | Ehsan Shams, project owner; approval recorded on their instruction after a written recommendation; legal name/organizational role not supplied | N/A - approved 2026-08-08 | M3 final auth; M12 security review; M13 production | Open_ADR_Register.md:10; 12_Security_RBAC_Audit.md:2553-2554; 13_DevOps_Deployment_Operations.md:2473 |
| ADR-002 | Production hosting provider, region, and topology | Core / Operations | ADR-OPS-001; ADR-SEC-012 | **Resolved 2026-08-01.** ADR-OPS-001 → ADR-002. ADR-SEC-012 spans two canonicals and is split: hosting region and topology → ADR-002, administrative network restriction → OPS-004, which already lists it. Neither canonical is satisfied by the alias alone. | Local/staging only; no production environment commitment or procurement. | TBD | TBD | TBD | M12 production-like hardening; M13 production | Open_ADR_Register.md:11; 13_DevOps_Deployment_Operations.md:2469; 12_Security_RBAC_Audit.md:2564 |
| ADR-003 | Production private-file storage adapter and location | Core / File storage | ADR-OPS-002 | proposed_mapping | Use the storage abstraction; local pilot storage is non-production unless backup and restore evidence passes. | TBD | TBD | TBD | M4 production adapter; M12 restore; M13 production | Open_ADR_Register.md:12; 13_DevOps_Deployment_Operations.md:2470 |
| ADR-004 | RPO, RTO, backup schedule, restore authority, and ownership | Core / Recovery | ADR-OPS-003; ADR-OPS-004; ADR-SEC-013 | **Resolved 2026-08-01.** ADR-OPS-003 → ADR-004; ADR-SEC-013 → ADR-004. ADR-OPS-004 is a subset covering backup design only; deciding it leaves RPO/RTO targets, restore authority and ownership open, so ADR-004 is not satisfied until those are decided and a restore drill passes. | Production release is blocked; backup claims are invalid until a clean full restore drill succeeds. | TBD | TBD | TBD | M12 restore drill; M13 production | Open_ADR_Register.md:13; 13_DevOps_Deployment_Operations.md:2471-2472; 12_Security_RBAC_Audit.md:2565 |
| ADR-005 | Retention, deletion, legal hold, and approval governance | Core / Data governance | ADR-OPS-010; ADR-SEC-011 | proposed_mapping | No automated purge or retention reduction; preserve legal-hold capability and historical financial evidence. | TBD | TBD | TBD | M11 retention jobs; M12/M13 production governance | Open_ADR_Register.md:14; 13_DevOps_Deployment_Operations.md:2478; 12_Security_RBAC_Audit.md:2563 |
| ADR-006 | Business timezone and Jalali/Gregorian input/display rules | Core / Localization and time | None found | none | **Approved:** store/transport UTC; canonical API values are Gregorian/ISO; use `Asia/Tehran` for business-day/cutoff/date-only interpretation; retain raw external values and never guess ambiguity. | Not supplied | Not supplied | N/A — approved 2026-07-20 | Approved baseline for M0 serialization and M5/M10 date-sensitive workflows; implementation evidence still required | ADR-006_Business_Timezone_and_Calendar_Rules.md; Open_ADR_Register.md:15 |
| ADR-007 | Initial bank profiles, verified templates, mappings, limits, and source accounts | Core / Banking | ADR-OPS-012 | proposed_mapping | Synthetic fixtures only; no real final export UAT or production bank output. | TBD | TBD | TBD | M4 bank configuration; M7 export UAT; M13 production | Open_ADR_Register.md:16; 13_DevOps_Deployment_Operations.md:2480 |
| ADR-008 | Malware scanning and quarantine policy | Core / File security | ADR-OPS-007; ADR-SEC-006 | proposed_mapping | Quarantine or deny production use when scan status cannot satisfy the approved policy; never treat an unchecked file as available evidence. | TBD | TBD | TBD | M4 file lifecycle; M12 production file acceptance | Open_ADR_Register.md:17; 13_DevOps_Deployment_Operations.md:2475; 12_Security_RBAC_Audit.md:2558 |
| ADR-009 | Manager strong/recent authentication factor and validity period | Core / Approval security | ADR-OPS-006; ADR-SEC-003; ADR-SEC-004 | **Resolved 2026-08-01.** ADR-OPS-006 → ADR-009; ADR-SEC-004 → ADR-009. ADR-SEC-003 is broader: the part about the manager approval factor maps to ADR-009, while general workforce MFA is not a Phase 1A canonical decision and is recorded as out of scope. Until it is decided, no MFA coverage may be claimed for non-approval sign-in. | Do not enable production manager approval without approved recent-auth assurance; no bypass. | TBD | TBD | TBD | M7 approval production gate; M12/M13 | Open_ADR_Register.md:18; 13_DevOps_Deployment_Operations.md:2474; 12_Security_RBAC_Audit.md:2555-2556 |
| POL-001 | Text-only outgoing payment confirmation | Business / Evidence policy | ADR-011; ADR-SEC-008 | proposed_mapping | Disabled. A paid confirmation requires approved evidence behavior. | TBD | TBD | TBD | M9 result confirmation; UAT/production | Open_ADR_Register.md:24; 15_Agent_Implementation_Plan.md:234; 12_Security_RBAC_Audit.md:2560 |
| POL-002 | Control for correcting a published paid result | Business / Correction authority | ADR-012; ADR-SEC-009 | proposed_mapping | **Approved for Phase 1A:** manager authority or dual control is required; the accountant-only default is rejected. The previous publication and its evidence are preserved and `payment_publication.correct` keeps `default_roles: []` with preparer and approver split. The recent-auth factor stays with ADR-009. | Not supplied | Not supplied | N/A — approved 2026-08-01 | M9 correction and UAT must prove the control cannot be configured off | Open_ADR_Register.md:25; 15_Agent_Implementation_Plan.md:235; 12_Security_RBAC_Audit.md:2561 |
| POL-003 | IBAN masking by role and publication type | Business / Privacy | ADR-013; ADR-SEC-007 | proposed_mapping | Least disclosure; do not expose full IBAN unless an explicit role and publication policy allows it. | TBD | TBD | TBD | M9 publication UI/API; M12 security acceptance | Open_ADR_Register.md:26; 15_Agent_Implementation_Plan.md:236; 12_Security_RBAC_Audit.md:2559 |
| POL-004 | Gold dispatch override | Business / Gold settlement | None found | none | No ungoverned override; dispatch remains blocked unless normal guards pass. | TBD | TBD | TBD | M10 dispatch workflow and UAT | Open_ADR_Register.md:27 |
| POL-005 | Break-glass access | Security policy | ADR-010; ADR-SEC-005; ADR-OPS-014 | Alias mappings still need_mapping because each alias combines break-glass with separation-of-duty or release authority | **Approved for Phase 1A:** disabled; no route, grant, flag, runtime activation, universal financial super-admin, or SoD bypass. Future enablement requires a new explicit decision. | Not supplied | Not supplied | N/A — approved 2026-07-20 | M3/M7/M12 must prove disabled behavior and mandatory SoD | FINANCIAL_INTEGRITY_BASELINE.md §5; Open_ADR_Register.md:28 |
| POL-006 | Production file size/type limits | Security / Capacity policy | ADR-014; ADR-OPS-008 | ADR-014 proposed_mapping but broader because it adds operational volume; ADR-OPS-008 proposed_mapping | No guessed production values; use conservative development-only limits and block production acceptance/load sign-off. | TBD | TBD | TBD | M4/M8 file processing; M12 load/security gate | Open_ADR_Register.md:29; 15_Agent_Implementation_Plan.md:237; 13_DevOps_Deployment_Operations.md:2476 |
| POL-007 | Formal accessibility conformance target | Product / Accessibility policy | None found | none | Accessibility checks remain required, but no formal conformance claim is made before approval. | TBD | TBD | TBD | M12 accessibility acceptance; M13 client acceptance | Open_ADR_Register.md:30 |
| OPS-001 | Production secret-management mechanism and rotation procedure | Operations / Secrets | None found; ADR-OPS-001 is a different hosting decision | none; numeric collision must not be treated as alias | No production secrets in source, images, or frontend; production deployment remains blocked. | TBD | TBD | TBD | M12/M13 production deployment | Open_ADR_Register.md:36; 13_DevOps_Deployment_Operations.md:2469 |
| OPS-002 | Monitoring, error reporting, alert routing, and data scrubbing | Operations / Observability | ADR-OPS-009; ADR-SEC-015 | proposed_mapping | Use structured redacted diagnostics only; no production-readiness claim until alert owners and destinations exist. | TBD | TBD | TBD | M11 observability; M12 operations sign-off | Open_ADR_Register.md:37; 13_DevOps_Deployment_Operations.md:2477; 12_Security_RBAC_Audit.md:2567 |
| OPS-003 | Production domains, origins, cookie scope, TLS termination, and HSTS rollout | Operations / Edge security | ADR-OPS-005; ADR-SEC-001 | **Resolved 2026-08-01.** Both aliases are shared with ADR-001 and are split by concern, not by ID: cookie scope, allowed origins, TLS termination and HSTS rollout → OPS-003; the authentication and session transport mechanism → ADR-001. Deciding one side never closes the other. | Development/staging origins only; deny broad origins and do not finalize production cookies/TLS/HSTS. | TBD | TBD | TBD | M3 auth deployment; M12/M13 production | Open_ADR_Register.md:38; 13_DevOps_Deployment_Operations.md:2473; 12_Security_RBAC_Audit.md:2553 |
| OPS-004 | Admin network restriction, VPN, or IP allowlist | Operations / Network security | ADR-OPS-011; ADR-SEC-012 | proposed_mapping | Do not expose administrative surfaces broadly in production; security sign-off remains blocked. | TBD | TBD | TBD | M3/M12 security sign-off | Open_ADR_Register.md:39; 13_DevOps_Deployment_Operations.md:2479; 12_Security_RBAC_Audit.md:2564 |
| OPS-005 | Log, security-event, and audit-view retention | Operations / Log governance | ADR-OPS-013; ADR-SEC-010 | proposed_mapping | Do not shorten or purge security/audit history; use least-access views. | TBD | TBD | TBD | M11 operations; M12 sign-off | Open_ADR_Register.md:40; 13_DevOps_Deployment_Operations.md:2481; 12_Security_RBAC_Audit.md:2562 |
| OPS-006 | Notification provider and delivery policy | Operations / Notifications | None found | none | In-app notification only; external providers and channels remain disabled. | TBD | TBD | TBD | M11 external notification activation; no Phase 1A block while disabled | Open_ADR_Register.md:41 |
| PKG-001 | Supported browser and OS matrix | Packaging / Client support | None found | none | Do not claim formal client support beyond tested development/staging targets. | TBD | TBD | TBD | M12/M13 client acceptance | Open_ADR_Register.md:42 |
| PKG-002 | Android package identity, distribution channel, and signing-key custody | Packaging / Android | None found | none | Android packaging disabled; Trader PWA remains the Phase 1A client. | TBD | TBD | TBD | Future Android packaging gate; no Phase 1A block | Open_ADR_Register.md:43 |
| PKG-003 | Windows signing, updater, and supported OS lifecycle | Packaging / Windows | None found | none | Windows packaging disabled; Admin Web remains the Phase 1A client. | TBD | TBD | TBD | Future Windows packaging gate; no Phase 1A block | Open_ADR_Register.md:44 |
| ADR-AI-001 | Approved provider or deployment model | AI / Provider governance | ADR-OPS-015 | needs_mapping because ADR-OPS-015 is a composite operations decision | All AI providers disabled; no production financial data is transmitted. | TBD | TBD | TBD | Phase 1B entry; no Phase 1A block while disabled | Open_ADR_Register.md:52; 13_DevOps_Deployment_Operations.md:2483 |
| ADR-AI-002 | Allowed input scope and data minimization | AI / Privacy | ADR-SEC-014; ADR-OPS-015 | ADR-SEC-014 proposed_mapping; ADR-OPS-015 needs_mapping because it is composite | No production input leaves the platform; use synthetic/anonymized/redacted evaluation data only. | TBD | TBD | TBD | Phase 1B entry | Open_ADR_Register.md:53; 12_Security_RBAC_Audit.md:2566; 13_DevOps_Deployment_Operations.md:2483 |
| ADR-AI-003 | Raw provider-output retention | AI / Retention | ADR-OPS-015 | needs_mapping because raw-output retention is only one part of the composite alias | Provider disabled and no raw provider output retained; test artifacts follow explicit fixture policy. | TBD | TBD | TBD | Phase 1B design/release | Open_ADR_Register.md:54; 13_DevOps_Deployment_Operations.md:2483 |
| ADR-AI-004 | Evaluation thresholds and release criteria | AI / Evaluation | None found | none | No AI capability progresses beyond offline experimentation or is shown as approved. | TBD | TBD | TBD | Phase 1B shadow/limited rollout gate | Open_ADR_Register.md:55 |
| ADR-AI-005 | Shadow and limited rollout policy | AI / Rollout | ADR-OPS-015 | needs_mapping because rollout is only one part of the composite alias | No production rollout; feature flags remain off and manual flow remains authoritative. | TBD | TBD | TBD | Phase 1B rollout gate | Open_ADR_Register.md:56; 13_DevOps_Deployment_Operations.md:2483 |
| ADR-AI-006 | Training-data and fine-tuning governance | AI / Data governance | None found | none | No training or fine-tuning on production data or corrections. | TBD | TBD | TBD | Phase 2 training/evaluation gate | Open_ADR_Register.md:57 |
| ADR-AI-007 | AI interaction with text-only exception policy | AI / Evidence policy | ADR-SEC-008 | needs_mapping because ADR-SEC-008 primarily maps to POL-001 | AI cannot create or justify a text-only financial confirmation; both features remain disabled. | TBD | TBD | TBD | Phase 1B/2 evidence-assistance release | Open_ADR_Register.md:58; 12_Security_RBAC_Audit.md:2560 |
| ADR-AI-008 | Production cost limits and alert ownership | AI / Cost operations | ADR-OPS-015 | needs_mapping because cost is one part of the composite alias | No production AI spend; provider feature flags remain off. | TBD | TBD | TBD | Phase 1B provider rollout | Open_ADR_Register.md:59; 13_DevOps_Deployment_Operations.md:2483 |

## Count control

| Category | Count |
|---|---:|
| Core ADR | 9 |
| Business and security policy | 7 |
| Operations | 6 |
| Packaging | 3 |
| AI ADR | 8 |
| Total | 33 |
| Approved | 4 |
| Open | 29 |

## Unrepresented or composite alias scopes

The following alias scopes do not have a clean one-to-one canonical row and require explicit owner mapping:

- ADR-010 and ADR-SEC-005 combine separation-of-duty exceptions with break-glass; POL-005 covers only the break-glass portion.
- ADR-014 combines file limits with operational volume; POL-006 names file size/type limits but not the complete volume/capacity decision.
- ADR-OPS-004 separates backup design from ADR-004, whose canonical scope also includes RPO/RTO and ownership.
- ADR-OPS-005 and ADR-SEC-001 span both ADR-001 session design and OPS-003 deployment-domain/cookie concerns.
- ADR-OPS-014 combines release approval and break-glass.
- ADR-OPS-015 combines multiple AI provider, privacy, retention, cost, incident, and rollout topics.
- ADR-SEC-008 overlaps POL-001 and ADR-AI-007.

No alias mapping in this file is resolved until explicit approval evidence is recorded and
the affected source documents are synchronized. Approval identity must be recorded exactly
as supplied; a legal name or organizational role must never be inferred.
