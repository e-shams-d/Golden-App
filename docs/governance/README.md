# M0 Governance Package

Status: WORKING BASELINE — scoped decisions approved; M0 approvals still required
Last validated: 2026-07-20

This directory converts the implementation documents into reviewable and
machine-readable M0 controls. Approved decision baselines govern their exact conflict
scope; they do not constitute blanket approval of the source package or authorize work
still blocked by another decision, conflict, catalogue, or milestone gate.

## Start here

1. M0_READINESS.md — current gate and remaining approvals.
2. DOCUMENT_APPROVAL_REGISTER.md — document authority versus recorded owner sign-off.
3. ../adr/ADR_INDEX.md — 33 canonical decisions: ADR-006, POL-005 and POL-002 Approved, 30 Open, plus alias mapping.
4. CONFLICT_REGISTER.md — 35 conflicts: 14 Resolved/Approved and 21 Open, none Critical.
5. status_catalog.yaml — 23 aggregates and 156 states from document 06.
6. permission_catalog.yaml — 118 canonical permissions, roles, constraints, and API aliases.
7. api_error_catalog.yaml — 25 stable API error codes.
8. command_catalog.yaml — 52 critical command envelopes and their blockers.
9. audit_outbox_catalog.yaml — 57 audit actions and 11 outbox events.
10. MONEY_TIME_CONTRACT.md — approved integer-IRR, UTC, and `Asia/Tehran` baseline plus remaining details.
11. FINANCIAL_INTEGRITY_BASELINE.md — approved export, allocation, recent-auth, audit, and SoD designs.
12. REPOSITORY_BASELINE.md — approved layout/PostgreSQL 16 baseline plus remaining runtime choices.
13. TRACEABILITY_MATRIX.md — M0-M13 and six required end-to-end flows.
14. M0_MANIFEST.json — file inventory, byte/line counts, and SHA-256 checksums.

## Machine-readable authority

- status_catalog.yaml: document 06 controls state names and transitions.
- permission_catalog.yaml: document 12 controls permission names and baseline grants.
- api_error_catalog.yaml: document 05 controls the API error envelope and codes.
- command_catalog.yaml: provisional integration of documents 05, 06, 10, and 12.
- audit_outbox_catalog.yaml: provisional catalogue from documents 10 and 12.

All machine-readable catalogues remain `provisional_pending_m0_approval`; the scoped
decisions recorded on 2026-07-20 do not approve the catalogues as a whole. Unknown
permissions, aliases, statuses, or commands fail closed. A compatibility alias may not
broaden authorization or silently change state.

## Validation result

The working package has been checked for:

- valid UTF-8 and YAML/JSON-compatible syntax;
- unique command IDs, error codes, audit actions, and outbox events;
- command permission references present in the permission catalogue;
- command audit/outbox references present in their catalogues;
- 23 status aggregates and 156 unique documented states;
- 715 explicit source references resolving to existing implementation/M0 documents and valid line numbers.

Validation proves structural consistency only. Decision approval evidence is recorded in
the cited ADR/baselines as: workspace owner approval via conversation; legal
name/organizational role not supplied. It does not imply approval of unrelated business,
security, privacy, bank, retention, catalogue, or production decisions.

## Change protocol

1. Change the highest topic authority first.
2. Update the corresponding M0 catalogue/register.
3. Update DB/API/backend/frontend/security/QA references.
4. Regenerate OpenAPI/clients/migrations when they exist.
5. Re-run structural and traceability validation.
6. Record owner approval and source hashes.
