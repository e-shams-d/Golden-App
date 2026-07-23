# Document Approval Register

Status: PROVISIONAL — scoped decision approval recorded; full document sign-off not recorded
Last reviewed: 2026-07-20

The documentation index declares documents 00 through 22 authoritative by topic.
This register separately tracks whether explicit owner approval evidence exists.
A declaration inside a document is not a substitute for a recorded human sign-off.

The 2026-07-20 conversation approved six scoped M0 decision groups, not documents 00–22
as complete baselines. Accordingly, every full-document row remains `Missing` below.

| ID | Topic | Header status summary | Index authority | Owner sign-off evidence | M0 action |
|---:|---|---|---|---|---|
| 00 | Master blueprint | Pending final project-owner approval | Authoritative | Missing | Project owner signs scope/baseline |
| 01 | Product requirements | Pending final project-owner approval | Authoritative | Missing | Product/project owner signs requirements |
| 02 | Domain and business rules | Pending final project-owner approval | Authoritative | Missing | Business/domain owner signs invariants |
| 03 | System architecture | Reviewed baseline | Authoritative | Missing | Technical lead records acceptance |
| 04 | Database schema | Authoritative baseline | Authoritative | Missing | Database/domain/security review evidence |
| 05 | API specification | Authoritative baseline | Authoritative | Missing | Backend/frontend/security/QA acceptance |
| 06 | Workflows/state machines | Authoritative baseline | Authoritative | Missing | Domain/product/QA state catalogue sign-off |
| 07 | UI/UX specification | Authoritative baseline | Authoritative | Missing | Product/UX acceptance |
| 08 | Bank processing | Authoritative baseline | Authoritative | Missing | Finance/bank operations acceptance |
| 09 | OCR/AI | Candidate for project-owner approval | Optional AI authority | Missing | Confirm future-only status for Phase 1A |
| 10 | Backend guide | Authoritative supporting baseline | Supporting authority | Missing | Backend/architecture acceptance |
| 11 | Frontend guide | Authoritative supporting baseline | Supporting authority | Missing | Frontend/security acceptance |
| 12 | Security/RBAC/Audit | Authoritative baseline | Authoritative | Missing | Security/business owner acceptance |
| 13 | DevOps/operations | Authoritative baseline | Authoritative | Missing | Operations/security acceptance |
| 14 | QA/acceptance | Reviewed baseline | Authoritative | Missing | QA/release owner acceptance |
| 15 | Implementation plan | Authoritative baseline | Authoritative | Missing | Technical/project lead acceptance |
| 16 | Documentation index | Authoritative governance baseline | Authoritative | Missing | Project/technical lead acceptance |
| 17 | Future roadmap | Authoritative future baseline | Authoritative | Missing | Product owner acceptance |
| 18 | Production runbook | Authoritative baseline | Authoritative | Missing | Operations/release owner acceptance |
| 19 | Client packaging | Authoritative baseline | Authoritative | Missing | Product/operations acceptance |
| 20 | Agent instructions | Authoritative baseline | Authoritative | Missing | Technical lead acceptance |
| 21 | UI design system | Authoritative baseline | Authoritative | Missing | Product/UX/frontend acceptance |
| 22 | UX journeys | Authoritative baseline | Authoritative | Missing | Product/UX/QA acceptance |

## Package note

Document 23 is referenced as governed historical discovery evidence but is absent from
the current implementation-only package. It is not an implementation authority. The
next documentation release manifest must state explicitly whether it is intentionally
excluded or separately archived.

## Required approval evidence

Each approval record must contain:

- document ID and SHA-256;
- approved version;
- approver name and role;
- approval date;
- accepted exceptions or open conflicts;
- affected ADR IDs;
- next review trigger.

## Scoped M0 decision approval record

Approval date: 2026-07-20
Approval evidence: workspace owner approval via conversation; legal name/organizational role not supplied

| Approved scope | Normative record | Conflict/ADR effect |
|---|---|---|
| Canonical `services/backend` + `infra` layout | `REPOSITORY_BASELINE.md` | `DOC-CONFLICT-009` Resolved — Approved |
| PostgreSQL 16 in every environment | `REPOSITORY_BASELINE.md` | `DOC-CONFLICT-022` Resolved — Approved |
| Integer IRR and UTC persistence/transport | `MONEY_TIME_CONTRACT.md` | M0 contract approved |
| `Asia/Tehran` business timezone and calendar boundary | `../adr/ADR-006_Business_Timezone_and_Calendar_Rules.md` | ADR-006 Approved |
| Mandatory outgoing-batch `finalizer != approver`; break-glass disabled | `FINANCIAL_INTEGRITY_BASELINE.md` §5 | `DOC-CONFLICT-021` Resolved — Approved |
| Separate export job/artifact; DB allocation; bound recent-auth context; explicit/versioned audit | `FINANCIAL_INTEGRITY_BASELINE.md` §§1–4 | `DOC-CONFLICT-017` through `DOC-CONFLICT-020` Resolved — Approved |

This record intentionally does not invent an approver legal name or organizational role.
It is sufficient evidence for the listed workspace implementation decisions, but it does
not satisfy the full-document sign-off fields above or production/UAT approval.
