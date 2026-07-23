# Money and Time Contract

Status: APPROVED BASELINE
Decision: ADR-006 approved for the Phase 1A platform-wide timezone/calendar boundary
Last reviewed: 2026-07-20
Decision evidence: workspace owner approval via conversation; legal name/organizational role not supplied

## Fixed money rules

1. Canonical monetary storage is integer IRR.
2. PostgreSQL financial columns use BIGINT unless an approved schema exception requires NUMERIC(20,0).
3. Binary floating point is forbidden for monetary input, calculation, transport, and comparison.
4. The original entered value and selected unit are retained.
5. Supported entered units for Phase 1A are IRR and TOMAN.
6. TOMAN to IRR conversion is exact multiplication by ten.
7. The unit is never inferred from number magnitude, formatting, actor, or page context.
8. API monetary values are base-10 integer strings.
9. Frontends use BigInt or an integer-safe decimal representation; JavaScript Number is forbidden for financial amounts.
10. Paid aggregation is exact. Overpayment creates reconciliation work and cannot be normalized into success.

## Canonical API representation

~~~json
{
  "amount_irr": "1250000000",
  "entered_amount": "125000000",
  "entered_unit": "TOMAN"
}
~~~

The server must reject a payload when entered_amount, entered_unit, and amount_irr do
not agree exactly.

## Fixed timestamp rules

1. Persist application timestamps as timezone-aware TIMESTAMPTZ values normalized to UTC.
2. API timestamps use ISO 8601 UTC representation.
3. Raw bank date/time strings are retained separately from normalized timestamps.
4. Ambiguous or unparseable bank dates are not guessed; they enter manual review.
5. Business/cutoff calculations use an explicit IANA timezone, never server-local time.
6. UI date rendering may be Jalali, but transport and persistence remain Gregorian/UTC.

## Approved runtime configuration

- `BUSINESS_TIMEZONE` is `Asia/Tehran` in local, CI, staging, and production environments.
- Production and staging fail readiness when `BUSINESS_TIMEZONE` is unset or differs from `Asia/Tehran`.
- The IANA timezone database, not a hard-coded offset, must determine historical/future offsets.
- Bank profile versions retain the timezone and rule/config version used for each evaluated split/export.

## Open decisions

- Screen-by-screen Jalali input controls and the allowed date-only contexts.
- Bank cutoff date conventions and holiday/calendar ownership.
- Display timezone for each role and exported report.
- Rules for date-only bank values and end-of-day interpretation.
- Whether a trader may enter Jalali dates directly or only select them through UI controls.

These remaining UX and bank-policy questions cannot change the approved canonical
contracts: integer IRR for money, UTC for stored/transported timestamps, Gregorian/ISO API
values, and `Asia/Tehran` for business-day/cutoff interpretation.

## Approval record

- Approval date: 2026-07-20
- Approval evidence: workspace owner approval via conversation; legal name/organizational role not supplied
- Approved scope: integer IRR, exact entered-unit provenance, UTC persistence/transport, and `Asia/Tehran` business timezone
- Decision record: `docs/adr/ADR-006_Business_Timezone_and_Calendar_Rules.md`

## Sources

- Implementation Docs/01_Product_and_Domain/02_Domain_Model_and_Business_Rules.md:1571
- Implementation Docs/02_Architecture_and_Contracts/04_Database_Schema.md:118
- Implementation Docs/02_Architecture_and_Contracts/05_API_Specification.md:187
- Implementation Docs/00_Start_Here/15_Agent_Implementation_Plan.md:134
