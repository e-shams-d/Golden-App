# Architecture and Policy Decisions

This directory contains the canonical project decision records created during M0.

- ADR_INDEX.md is the working register and cross-document alias map.
- ADR_TEMPLATE.md is the required template for a decision record.
- Open decisions remain Open until approval evidence is recorded and affected contracts
  are synchronized. ADR-006 and the Phase 1A outcome for POL-005 are approved; their
  evidence deliberately does not infer a legal name or organizational role that was not
  supplied.

The canonical IDs currently come from
Implementation Docs/00_Start_Here/Open_ADR_Register.md. ADR-SEC, ADR-OPS, and the
ADR-010..014 references are aliases only until their mappings are approved.

## Decision workflow

1. Assign owner name, owner role, and due date.
2. State the exact decision boundary and affected milestones.
3. Record considered options and security/financial implications.
4. Select a decision and safe rollback/transition plan.
5. Update every affected authoritative document.
6. Update catalogues, OpenAPI, migrations, clients, tests, and traceability.
7. Record approval evidence and close the index row.

## Approved records

- `ADR-006_Business_Timezone_and_Calendar_Rules.md` — Approved 2026-07-20.
- `POL-005` — Phase 1A break-glass disabled; recorded in
  `../governance/FINANCIAL_INTEGRITY_BASELINE.md` §5 and indexed in `ADR_INDEX.md`.
