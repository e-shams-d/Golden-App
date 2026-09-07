/**
 * Telling the centre you have paid for gold.
 * §17.3 (`15_Agent_Implementation_Plan.md:1958`).
 *
 * M11 Screens, slice 6. M10 built this command and no trader has ever used it.
 *
 * **A claim, not a fact.** The trader states an amount and a tracking number; the centre finds the
 * bank row that proves it and confirms what actually arrived. The two are separate tables for that
 * reason, and `permission_catalog.yaml` gives a trader nothing on the matching surface — a trader
 * who could name the proving row would be deciding their own case.
 *
 * **No `If-Match`**, and the contract agrees: submitting a claim creates a row that did not exist.
 * `Idempotency-Key` is still required, because a double-submitted form must not become two claims
 * for one payment.
 *
 * **Separate from the admin module by `UI-ISO-001`**, and here it is nearly all that separates
 * them: this file names one path, and the centre's names five the trader may not call.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

function commandKey(): string {
  return globalThis.crypto.randomUUID();
}

/** What comes back when a claim is filed. */
export type IncomingReceipt = Readonly<{
  id: string;
  gold_sale_order_id: string;
  status: string;
  amount_irr: number;
  confirmed_amount_irr: number | null;
  tracking_number: string | null;
  evidence_file_id: string | null;
  order_status: string;
  record_version: number;
  created_at: string;
}>;

export type ReceiptClaim = Readonly<{
  amountIrr: number;
  trackingNumber?: string | null;
  senderName?: string | null;
  sourceBankName?: string | null;
  rawPaymentDate?: string | null;
  evidenceFileId?: string | null;
}>;

/**
 * File the claim against one gold order.
 *
 * **`amount_irr` is the only required field**, which is the contract's judgement and a kind one: a
 * person who has just transferred money should not be blocked from saying so because they cannot
 * find the tracking number on their bank's receipt. Everything else helps the accountant find the
 * matching row and is optional.
 *
 * The amount is a number here rather than a string, because the contract types it as an integer —
 * rials have no minor unit, so there is no decimal to lose. That is the opposite of `gold_weight`
 * and the difference is real rather than an inconsistency.
 */
export async function submitReceipt(
  orderId: string,
  claim: ReceiptClaim,
): Promise<IncomingReceipt> {
  const response = await transport.request<IncomingReceipt, Record<string, unknown>>({
    method: "POST",
    path: `/gold-sale-orders/${orderId}/incoming-payment-receipts`,
    body: {
      amount_irr: claim.amountIrr,
      tracking_number: claim.trackingNumber ?? null,
      sender_name: claim.senderName ?? null,
      source_bank_name: claim.sourceBankName ?? null,
      raw_payment_date: claim.rawPaymentDate ?? null,
      evidence_file_id: claim.evidenceFileId ?? null,
    },
    idempotencyKey: commandKey(),
  });
  return response.data;
}
