/**
 * A trader's claim that they paid, and the centre's judgement about it.
 * §17.3 (`15_Agent_Implementation_Plan.md:1958`), §17.4 (`:1969`), §17.5 (`:1982`).
 *
 * M11 Screens, slice 6. M10 built every command here and nothing has ever proposed a match or
 * confirmed a payment from a screen.
 *
 * **Internal only, and there is no trader half of this module.** A trader may claim they paid —
 * that is `submitIncomingPaymentReceipt`, on their own order — and may not say which bank row
 * proves it. `permission_catalog.yaml` gives them neither `incoming_payment.match` nor
 * `incoming_receipt.read`, and the reason is not only authorisation: which row proves a claim is
 * the centre's judgement, and a trader who could propose one would be deciding their own case.
 *
 * **Two preconditions, two aggregates, and slice 5 recorded one of them wrongly.** Confirming
 * takes `If-Match` against the *receipt*; rejecting a match takes it against the *match*. Slice 5's
 * precondition gate recorded both as the receipt's, and reading the routes while building this
 * screen is what found it — so slice 6 added two reads rather than one.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** A fresh key per attempt, so a retry of *this* click replays and a second click is second. */
function commandKey(): string {
  return globalThis.crypto.randomUUID();
}

/** One claim, as the accountant reviewing it sees it. */
export type IncomingReceipt = Readonly<{
  id: string;
  gold_sale_order_id: string;
  status: string;
  amount_irr: number;
  /** What the centre agreed had arrived. `null` until somebody confirms — not zero. */
  confirmed_amount_irr: number | null;
  tracking_number: string | null;
  evidence_file_id: string | null;
  order_status: string;
  record_version: number;
  created_at: string;
}>;

export type ReceiptWithPrecondition = Readonly<{
  receipt: IncomingReceipt;
  ifMatch: string;
}>;

/**
 * One proposed match.
 *
 * **A rejected candidate is history rather than a deletion.** §10.7's shape is "multiple records
 * support partial/combined scenarios and corrections", so the list carries rejections too and the
 * screen renders them — history nobody can read is indistinguishable from a row that was removed.
 */
export type IncomingMatch = Readonly<{
  id: string;
  incoming_payment_receipt_id: string;
  bank_statement_row_id: string;
  status: string;
  match_method: string;
  match_score: string | null;
  match_reasons: readonly string[];
  confirmed_amount_irr: number | null;
  confirmed_at: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  replaces_match_id: string | null;
  receipt_status: string;
  record_version: number;
  created_at: string;
}>;

export type MatchWithPrecondition = Readonly<{
  match: IncomingMatch;
  ifMatch: string;
}>;

export async function readReceipt(
  receiptId: string,
  signal?: AbortSignal,
): Promise<ReceiptWithPrecondition> {
  const response = await transport.request<IncomingReceipt>({
    method: "GET",
    path: `/incoming-payment-receipts/${receiptId}`,
    ...(signal ? { signal } : {}),
  });
  if (!response.etag) {
    throw new Error("the read returned no ETag, so no command can be sent safely");
  }
  return { receipt: response.data, ifMatch: response.etag };
}

/** Every candidate proposed for this claim, oldest first — the sequence of judgements forwards. */
export async function listMatches(
  receiptId: string,
  signal?: AbortSignal,
): Promise<readonly IncomingMatch[]> {
  const response = await transport.request<readonly IncomingMatch[]>({
    method: "GET",
    path: `/incoming-payment-receipts/${receiptId}/matches`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * One match, read for its own precondition.
 *
 * **Not taken from the list**, and that is the whole reason this route exists. One `ETag` cannot
 * describe many rows, so rejecting straight from the list would mean building
 * `rv-${row.record_version}` out of a page that is already one request old — the defect
 * `apps/admin-web/test/preconditions-come-from-the-server.test.ts` was written for.
 */
export async function readMatch(
  receiptId: string,
  matchId: string,
): Promise<MatchWithPrecondition> {
  const response = await transport.request<IncomingMatch>({
    method: "GET",
    path: `/incoming-payment-receipts/${receiptId}/matches/${matchId}`,
  });
  if (!response.etag) {
    throw new Error("the read returned no ETag, so no command can be sent safely");
  }
  return { match: response.data, ifMatch: response.etag };
}

/**
 * Suggest which statement row proves this claim.
 *
 * **No `If-Match`, and the contract agrees**: a proposal creates a row rather than editing one,
 * and the unique constraint on the pair is what makes two simultaneous proposals safe. No
 * `match_method` either — Phase 1A has exactly one, a human searching, and a field would invite a
 * caller to claim a machine found it.
 */
export async function proposeMatch(
  receiptId: string,
  bankStatementRowId: string,
  reasons: readonly string[],
): Promise<IncomingMatch> {
  const response = await transport.request<IncomingMatch, Record<string, unknown>>({
    method: "POST",
    path: `/incoming-payment-receipts/${receiptId}/matches`,
    body: { bank_statement_row_id: bankStatementRowId, match_reasons: [...reasons] },
    idempotencyKey: commandKey(),
  });
  return response.data;
}

/**
 * Say a suggestion is wrong, and why.
 *
 * `ifMatch` is the *match's*, from `readMatch`. A reason is required and non-blank because §8.8
 * requires a match decision to record actor, time and reason — a rejection nobody can explain is
 * one nobody can review.
 */
export async function rejectMatch(
  receiptId: string,
  matchId: string,
  ifMatch: string,
  rejectionReason: string,
): Promise<IncomingMatch> {
  const response = await transport.request<IncomingMatch, { rejection_reason: string }>({
    method: "POST",
    path: `/incoming-payment-receipts/${receiptId}/matches/${matchId}/reject`,
    body: { rejection_reason: rejectionReason },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}

/**
 * What the confirmation moved, read from the published contract rather than assumed.
 *
 * **`confirmed_total_irr` and `expected_amount_irr` are the pair that matters**, and the response
 * carries both for a reason: what this payment settled is only meaningful against what the order
 * costs. A screen showing one without the other would let an accountant confirm a part payment
 * believing the order was closed.
 */
export type Confirmation = Readonly<{
  receipt_id: string;
  receipt_status: string;
  confirmed_amount_irr: number | null;
  /** Everything confirmed against the order so far, this payment included. Never null. */
  confirmed_total_irr: number;
  /** What the order is priced at. `null` when it has not been priced. */
  expected_amount_irr: number | null;
  order_status: string;
  record_version: number;
}>;

/**
 * Record that the money arrived, and what the order now totals.
 *
 * **A different permission from proposing.** `incoming_payment.match` proposes;
 * `incoming_payment.confirm` decides, and `permission_catalog.yaml` gives the manager a different
 * conditional on each — M0 saying the two acts are not one.
 *
 * `ifMatch` is the *receipt's*, from `readReceipt`. `confirmed_amount_irr` is what the accountant
 * agrees arrived, which may be less than claimed; an overpayment is refused by the server and
 * opens a review task, so the screen reports that refusal rather than pre-empting it.
 */
export async function confirmPayment(
  receiptId: string,
  ifMatch: string,
  input: Readonly<{
    incomingPaymentMatchId: string;
    confirmedAmountIrr: number;
    confirmationNote?: string | null;
  }>,
): Promise<Confirmation> {
  const response = await transport.request<Confirmation, Record<string, unknown>>({
    method: "POST",
    path: `/incoming-payment-receipts/${receiptId}/confirm`,
    body: {
      incoming_payment_match_id: input.incomingPaymentMatchId,
      confirmed_amount_irr: input.confirmedAmountIrr,
      confirmation_note: input.confirmationNote ?? null,
    },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}
