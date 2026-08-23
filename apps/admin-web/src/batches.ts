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

export type DecisionRecorded = Readonly<{
  approval: PriorDecision;
  batch: BatchSummary;
  version: VersionSummary;
  replayed: boolean;
}>;

/**
 * The two purposes a step-up may be obtained for, and they are not interchangeable.
 *
 * `FINANCIAL_INTEGRITY_BASELINE.md` §3 binds a context to an action as well as a resource, and
 * the two failures differ in kind: the wrong resource pays the wrong people, the wrong action
 * pays them when somebody meant to stop it. The strings are the command ids the server reads as
 * `purpose`.
 */
export const APPROVE_PURPOSE = "payment_batch_version.approve";
export const REJECT_PURPOSE = "payment_batch_version.reject";
export const STEP_UP_RESOURCE_TYPE = "payment_batch_version";

/**
 * Approve the exact version whose hash the caller quotes back.
 *
 * **`expectedContentHash` is a parameter, not something read here.** `05_API_Specification.md:1443`
 * — "The command is blocked when the content hash differs" — is the whole mechanism behind
 * "exact": the server does not assume the manager saw the current version, it requires them to
 * quote it. A function that fetched the hash before submitting would be quoting whatever is
 * current, which after a replacement is not what was reviewed. `UI-APPROVE-001`.
 *
 * **No `If-Match`.** `:1443` says none is needed for the immutable version, and the hash is the
 * stronger token: a record version says *when* the caller read, the hash says *what* they read.
 */
export async function approveVersion(input: {
  batchId: string;
  versionId: string;
  expectedContentHash: string;
  recentAuthReference: string;
  idempotencyKey: string;
  approvalNote?: string;
  signal?: AbortSignal;
}): Promise<DecisionRecorded> {
  const response = await transport.request<DecisionRecorded>({
    method: "POST",
    path: `/payment-batches/${encodeURIComponent(input.batchId)}/versions/${encodeURIComponent(input.versionId)}/approve`,
    body: {
      expected_content_hash: input.expectedContentHash,
      approval_note: input.approvalNote ?? null,
    },
    idempotencyKey: input.idempotencyKey,
    recentAuthToken: input.recentAuthReference,
    ...(input.signal ? { signal: input.signal } : {}),
  });
  return response.data;
}

/**
 * Reject it, with the reason `05_API_Specification.md:1461` makes mandatory.
 *
 * §13.6: "Rejection does not edit the version; a new replacement version may be created later."
 * Nothing here creates one — that is the accountant's command on a different screen.
 */
export async function rejectVersion(input: {
  batchId: string;
  versionId: string;
  expectedContentHash: string;
  recentAuthReference: string;
  idempotencyKey: string;
  reasonCode: string;
  reason: string;
  signal?: AbortSignal;
}): Promise<DecisionRecorded> {
  const response = await transport.request<DecisionRecorded>({
    method: "POST",
    path: `/payment-batches/${encodeURIComponent(input.batchId)}/versions/${encodeURIComponent(input.versionId)}/reject`,
    body: {
      expected_content_hash: input.expectedContentHash,
      reason_code: input.reasonCode,
      reason: input.reason,
    },
    idempotencyKey: input.idempotencyKey,
    recentAuthToken: input.recentAuthReference,
    ...(input.signal ? { signal: input.signal } : {}),
  });
  return response.data;
}

/**
 * Whether the version this page was rendered from is still the batch's current one.
 *
 * §13.4's trigger. Read from the freshly-fetched view rather than remembered, so a page open
 * while somebody replaces the version underneath it can tell — and `UI-STALE-002` is the reason
 * this is a pure function over two values: the decision must not depend on anything the dialog
 * closed over.
 */
export function isStale(renderedVersionId: string, current: ApprovalView): boolean {
  return current.version.id !== renderedVersionId;
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
  // A single-digit rial amount is a *fraction* of a Toman, not zero. Returning "0" for five rials
  // would be the same rounding this function exists to avoid, just at the small end.
  const whole = digits.length > 1 ? digits.slice(0, -1) : "0";
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
