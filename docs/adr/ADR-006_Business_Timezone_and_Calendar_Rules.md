# ADR-006 — Business timezone and calendar boundary rules

Status: Approved
Date: 2026-07-20
Decision owner role: Not supplied
Decision owner name: Not supplied
Blocking milestone/gate: M0 serialization contract; M5/M10 date-sensitive workflows
Canonical register ID: ADR-006
Related aliases: None

## Context

The source documents consistently require timezone-aware UTC persistence and transport,
but they did not select the IANA timezone used for business-day, cutoff, and date-only
interpretation. That omission blocked a deterministic Phase 1A money/time contract and
date-sensitive workflow tests.

## Decision drivers

- One deterministic business clock across local, CI, staging, and production environments.
- Preservation of exact instants and raw bank values.
- Correct historical and future offset handling without hard-coded offsets.
- A clean boundary between Persian user experience and canonical API/database values.
- Fail-closed handling of ambiguous external date/time values.

## Options considered

### Option A — UTC as both storage and business timezone

This is operationally simple, but it does not represent the approved business calendar
and cutoff context for the Phase 1A deployment.

### Option B — UTC persistence with Asia/Tehran business interpretation

Persist and transport exact instants in UTC, while using the IANA `Asia/Tehran` zone for
business-day, cutoff, and date-only interpretation. This retains unambiguous technical
timestamps without losing the business calendar context.

## Decision

Option B is approved for Phase 1A:

1. `BUSINESS_TIMEZONE` is pinned to the IANA identifier `Asia/Tehran` in every environment.
2. Application timestamps are stored as timezone-aware PostgreSQL `TIMESTAMPTZ` values and
   normalized to UTC. API timestamp values are ISO 8601 UTC values.
3. Business-day boundaries, cutoff evaluation, and date-only interpretation use
   `Asia/Tehran` through the installed IANA timezone database; a numeric fixed offset is
   forbidden.
4. Canonical API date/time input remains Gregorian/ISO. A UI may accept or display Jalali
   dates only through a deterministic conversion component; it sends canonical Gregorian
   dates or UTC instants to the API.
5. Raw external bank date/time text is retained with the parser/rule version. Ambiguous or
   unparseable values are never guessed and must enter manual review.
6. A bank profile version records the timezone and calendar/cutoff rule version used for
   each evaluated split, export, or import.
7. Production and staging readiness fail when the configured timezone differs from the
   approved value or the timezone database is unavailable.

This ADR selects the platform-wide timezone and calendar boundary. Bank-specific holiday
ownership, per-bank cutoff values, and screen-level UX copy remain separate configuration
or follow-up decisions and cannot override this ADR.

## Consequences

### Positive

- The same input produces the same business date in development, CI, and production.
- Storage and API values remain unambiguous and portable.
- Jalali presentation does not leak into database or transport contracts.
- Bank parsing failures remain visible and reviewable instead of silently shifting dates.

### Negative and risks

- Runtime images must include and update the IANA timezone database.
- Boundary and daylight-rule regression tests are required even when the current zone has
  no seasonal offset change.
- UI conversion libraries require compatibility tests against backend conversion behavior.

## Implementation impact

- Domain/business rules: pass an explicit business clock/timezone into date-sensitive rules.
- Database/migrations: use `TIMESTAMPTZ`; retain raw bank values and rule provenance.
- API/OpenAPI: use ISO 8601 UTC timestamps and Gregorian canonical dates.
- Backend: reject missing/mismatched timezone configuration in readiness-sensitive environments.
- Frontend: isolate Jalali conversion and never send locale-formatted timestamps.
- Security/RBAC: audit records use UTC instants; display conversion cannot alter evidence.
- Files/workers: persist parser, timezone, and calendar/cutoff rule versions.
- Operations/runbooks: pin `BUSINESS_TIMEZONE=Asia/Tehran` and verify tzdata availability.
- QA/UAT: cover UTC/local boundaries, date-only values, ambiguous input, and conversion round trips.

## Migration and rollback

Before financial data exists, all environments move directly to this baseline. Existing
test fixtures must be regenerated when they relied on server-local time. A later timezone
change requires a new ADR and forward migration/configuration version; historical instants
and recorded rule provenance are never rewritten.

## Acceptance evidence

- [x] ADR index updated.
- [x] Money/time baseline updated.
- [x] M0 readiness and conflict evidence updated.
- [x] Required implementation and test obligations identified.
- [x] Owner approval recorded.

## Approval

Approval evidence: workspace owner approval via conversation; legal name/organizational role not supplied
Approval date: 2026-07-20
Approved scope: integer IRR/UTC contract and `Asia/Tehran` business timezone described above
Approved package hashes: recorded in `docs/governance/M0_MANIFEST.json`

## Sources

- `Implementation Docs/00_Start_Here/Open_ADR_Register.md:15`
- `Implementation Docs/01_Product_and_Domain/02_Domain_Model_and_Business_Rules.md:1571`
- `Implementation Docs/02_Architecture_and_Contracts/04_Database_Schema.md:118`
- `Implementation Docs/02_Architecture_and_Contracts/05_API_Specification.md:187`
- `docs/governance/MONEY_TIME_CONTRACT.md`
