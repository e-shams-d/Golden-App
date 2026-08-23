/**
 * The approval queue and the exact version a manager decides on.
 *
 * Per-app rather than shared with the trader bundle, for the reason `src/payment-requests.ts`
 * gives: `UI-ISO-001` requires that neither bundle contain the other's endpoint paths, and the
 * cheapest guarantee is that neither bundle ever names one. A batch has no trader, so nothing
 * here has a counterpart on that side at all.
 *
 * **Nothing is derived here that the server derives.** `separation_of_duty` arrives decided,
 * `warning_count` arrives counted, and the three counts arrive computed from the version's own
 * items. A client-side `items.length` would answer a different question the moment a response is
 * paginated, and a client-side separation check would be a second opinion about a rule the
 * database enforces.
 *
 * **`content_hash` is carried, never recomputed and never re-read.** The approve command must
 * quote back the hash the screen was rendered with — `05_API_Specification.md:1443` calls it the
 * expected content hash — so this module hands it through unchanged. A screen that refreshed it
 * before submitting would be approving whatever is current rather than what was reviewed.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** One row of §13.2's queue. Every column that section names. */
export type QueueRow = Readonly<{
  id: string;
  batch_number: string;
  status: string;
  record_version: number;
  row_count: number;
  total_amount_irr: string;
  version_id: string | null;
  version_number: number | null;
  bank: string | null;
  source_account: string | null;
  mapping_version: number | null;
  warning_count: number;
  prepared_by: string | null;
  finalized_by: string | null;
  version_created_at: string | null;
}>;

export type BatchSummary = Readonly<{
  id: string;
  batch_number: string;
  status: string;
  record_version: number;
}>;

export type VersionSummary = Readonly<{
  id: string;
  version_number: number;
  status: string;
  row_count: number;
  total_amount_irr: string;
  content_hash: string;
  validation_summary: Readonly<Record<string, readonly string[]>>;
}>;

export type VersionItem = Readonly<{
  id: string;
  row_order: number;
  payment_attempt_id: string;
  amount_irr: string;
  beneficiary_name: string;
  beneficiary_iban: string;
  description: string | null;
  row_hash: string;
}>;

export type PriorDecision = Readonly<{
  id: string;
  decision: string;
  decided_at: string;
  approved_content_hash: string | null;
  reason: string | null;
}>;

/**
 * Whether this viewer may decide, and which rule refuses them.
 *
 * Advisory: the command refuses again and the database refuses after that. It exists so a screen
 * can explain a refusal rather than invite one.
 */
export type SeparationOfDuty = Readonly<{
  may_decide: boolean;
  reason: string | null;
}>;

export type ApprovalView = Readonly<{
  batch: BatchSummary;
  version: VersionSummary;
  items: readonly VersionItem[];
  prior_decision: PriorDecision | null;
  request_count: number;
  trader_count: number;
  beneficiary_count: number;
  bank: string | null;
  bank_profile_version_number: number | null;
  mapping_version: number | null;
  source_account: string | null;
  prepared_by: string | null;
  finalized_by: string | null;
  separation_of_duty: SeparationOfDuty;
  preview_export_id: string | null;
}>;

/**
 * The queue, or the whole history.
 *
 * `awaitingDecision` defaults to **true** because this is the approval queue and §13.4 needs the
 * history to stay *reachable*, not to be the default view. A manager opening the screen wants
 * what is waiting; the history is one control away.
 */
export async function listBatches(
  awaitingDecision = true,
  signal?: AbortSignal,
): Promise<readonly QueueRow[]> {
  const response = await transport.request<{ batches: readonly QueueRow[] }>({
    method: "GET",
    path: awaitingDecision ? "/payment-batches?awaiting_decision=true" : "/payment-batches",
    ...(signal ? { signal } : {}),
  });
  return response.data.batches;
}

export async function readApprovalView(
  batchId: string,
  versionId: string,
  signal?: AbortSignal,
): Promise<ApprovalView> {
  const response = await transport.request<ApprovalView>({
    method: "GET",
    path: `/payment-batches/${encodeURIComponent(batchId)}/versions/${encodeURIComponent(versionId)}/approval-view`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * IRR to Toman, for display only. S-1 in the screens plan.
 *
 * §13.3 asks for "total IRR and Toman equivalent". Toman is IRR ÷ 10 by definition, so there is
 * no rate and no rounding decision — but `MONEY_TIME_CONTRACT.md:17` makes IRR integer strings
 * the wire format, and a `total_amount_toman` on the wire would be a second monetary
 * representation of the same money. `tests/backend/test_approval_read_shape.py` asserts no field
 * transports it.
 *
 * String in, string out, and no `Number` anywhere: an IRR total can exceed `Number.MAX_SAFE_INTEGER`
 * at around nine quadrillion, and this platform's amounts are already in the trillions.
 */
export function tomanFromIrr(irr: string): string {
  const digits = irr.replace(/^0+(?=\d)/u, "");
  if (!/^\d+$/u.test(digits)) return irr;
  if (digits.length <= 1) return "0";
  const whole = digits.slice(0, -1);
  const remainder = digits.slice(-1);
  return remainder === "0" ? whole : `${whole}.${remainder}`;
}

/**
 * The first twelve characters of a digest, for a human to compare. S-2 in the plan.
 *
 * §13.3 asks for a "content hash fingerprint" rather than the hash, and a 64-character string is
 * not something anybody checks by eye. Twelve hex characters is 48 bits — enough that two
 * versions of one batch differing by accident is not a thing that happens, and short enough to
 * read aloud. The full value stays available; this is what is shown.
 */
export function fingerprint(hash: string): string {
  return hash.slice(0, 12);
}
