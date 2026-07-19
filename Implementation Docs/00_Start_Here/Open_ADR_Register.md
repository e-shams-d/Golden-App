# Open ADR and Decision Register

**Status:** Open items requiring named owners and approval during Milestone M0.  
**Rule:** An open ADR does not authorize a coding agent to invent an irreversible implementation choice.

## Core ADRs

| ID | Decision | Owner | Status | Blocks |
|---|---|---|---|---|
| ADR-001 | Browser authentication and session transport | TBD | Open | Auth implementation finalization |
| ADR-002 | Production hosting provider, region, and topology | TBD | Open | Production environment |
| ADR-003 | Production private-file storage adapter and location | TBD | Open | Production file deployment |
| ADR-004 | RPO, RTO, backup schedule, restore authority and ownership | TBD | Open | Production release |
| ADR-005 | Retention, deletion, legal hold, and approval governance | TBD | Open | Retention activation |
| ADR-006 | Business timezone and Jalali/Gregorian input/display rules | TBD | Open | Date-sensitive workflows |
| ADR-007 | Initial bank profiles, verified templates, mappings, limits, and source accounts | TBD | Open | Bank export UAT |
| ADR-008 | Malware scanning and quarantine policy | TBD | Open | Production file acceptance |
| ADR-009 | Manager strong/recent authentication factor and validity period | TBD | Open | Production manager approval |

## Business and security policy decisions

| Tracking ID | Decision | Safe default | Owner | Status |
|---|---|---|---|---|
| POL-001 | Text-only outgoing payment confirmation | Disabled | TBD | Open |
| POL-002 | Control for correcting a published paid result | Manager or dual control | TBD | Open |
| POL-003 | IBAN masking by role and publication type | Least disclosure | TBD | Open |
| POL-004 | Gold dispatch override | No ungoverned override | TBD | Open |
| POL-005 | Break-glass access | Disabled | TBD | Open |
| POL-006 | Production file size/type limits | No guessed values | TBD | Open |
| POL-007 | Formal accessibility conformance target | Select before production acceptance | TBD | Open |

## Operations and packaging decisions requiring ADR assignment

| Tracking ID | Decision | Owner | Blocks |
|---|---|---|---|
| OPS-001 | Production secret-management mechanism and rotation procedure | TBD | Production deployment |
| OPS-002 | Monitoring, error reporting, alert routing, and data scrubbing | TBD | Production operations |
| OPS-003 | Production domains, origins, cookie scope, TLS termination, and HSTS rollout | TBD | Authentication and deployment |
| OPS-004 | Admin network restriction, VPN, or IP allowlist | TBD | Security sign-off |
| OPS-005 | Log, security-event, and audit-view retention | TBD | Operations sign-off |
| OPS-006 | Notification provider and delivery policy | TBD | External notification activation |
| PKG-001 | Supported browser and OS matrix | TBD | Client acceptance |
| PKG-002 | Android package identity, distribution channel, and signing-key custody | TBD | Android packaging |
| PKG-003 | Windows signing, updater, and supported OS lifecycle | TBD | Windows packaging |

## AI ADRs

These are not Phase 1A launch blockers while all AI features remain disabled.

| ID | Decision | Owner | Status |
|---|---|---|---|
| ADR-AI-001 | Approved provider or deployment model | TBD | Open |
| ADR-AI-002 | Allowed input scope and data minimization | TBD | Open |
| ADR-AI-003 | Raw provider-output retention | TBD | Open |
| ADR-AI-004 | Evaluation thresholds and release criteria | TBD | Open |
| ADR-AI-005 | Shadow and limited rollout policy | TBD | Open |
| ADR-AI-006 | Training-data and fine-tuning governance | TBD | Open |
| ADR-AI-007 | AI interaction with text-only exception policy | TBD | Open |
| ADR-AI-008 | Production cost limits and alert ownership | TBD | Open |

## M0 completion requirement

Every blocking item must have a named decision owner, target date, status, decision record location, and affected-document update plan.
