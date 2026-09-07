/**
 * Handing the gold over, and closing the order.
 * §17.6, and `06_Workflows_and_State_Machines.md` §8.2's `dispatched --> received_by_trader`.
 *
 * M11 Screens, slice 7. M10 built recording a dispatch and closing an order; nothing has ever
 * done either from a screen.
 *
 * **No new read, and that is worth saying.** All three commands in this flow take `If-Match`
 * against the *order* — including the trader's acknowledgement, whose own route note says §8.2
 * moves both rows and the order is the aggregate. `getGoldSaleOrder` has issued that `ETag` since
 * slice 5, so this module reuses `src/gold-orders.ts`'s read rather than adding a fourth
 * precondition source.
 *
 * The gate slice 5 built is what makes that checkable rather than remembered: it answered "yes"
 * for this slice before a line was written, which is the first time it has paid rather than
 * caught.
 *
 * **The guard override is the one control here that changes what the system allows**, so it is the
 * one this module is most careful about. See `recordDispatch`.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** A fresh key per attempt, so a retry of *this* click replays and a second click is second. */
function commandKey(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * What a dispatch became, and what the order now stands at.
 *
 * `confirmed_total_irr` and `expected_amount_irr` travel together for the reason the confirmation
 * response gives: what has been paid is only meaningful against what the order costs. Here they
 * are also the pair the guard is about — dispatching gold for an order that is not fully paid is
 * the thing an override overrides, so a screen that showed one without the other would hide the
 * decision being made.
 */
export type Dispatch = Readonly<{
  id: string;
  gold_sale_order_id: string;
  dispatch_type: string;
  status: string;
  gold_weight: string | null;
  weight_unit: string | null;
  dispatched_at: string | null;
  guard_override_at: string | null;
  guard_override_reason: string | null;
  order_status: string;
  confirmed_total_irr: number;
  expected_amount_irr: number | null;
  record_version: number;
  created_at: string;
}>;

export type DispatchInput = Readonly<{
  dispatchType: string;
  goldWeight?: string | null;
  weightUnit?: string | null;
  goldPurity?: string | null;
  recipientName?: string | null;
  dispatchedAt?: string | null;
  trackingOrDeliveryNote?: string | null;
  evidenceFileId?: string | null;
  /**
   * Why the payment guard is being overridden, when it is.
   *
   * **Absent means "do not override".** An empty string would be a reason nobody wrote, recorded
   * as though somebody had — so the screen sends `null` unless a person typed one.
   */
  guardOverrideReason?: string | null;
}>;

/**
 * Record that the gold went out.
 *
 * **`If-Match` is the order's**, echoed from `readOrder`. Two warehouse operators dispatching the
 * same order is the case it exists for and it is not hypothetical: the queue shows that order to
 * everybody holding `gold_sale.dispatch`.
 *
 * **`guard_override_reason` is the only field here that changes what the system permits.** Without
 * it the server refuses to dispatch against an order that is not fully paid; with it the refusal
 * becomes a recorded override rather than a silent bypass — `guard_override_at` and the reason
 * both come back, which is what makes the decision reviewable afterwards. The screen therefore
 * treats it as a deliberate second step rather than one more optional field.
 *
 * The weight is a string like everywhere else: `MONEY_TIME_CONTRACT` rule 8's reasoning for
 * amounts holds for a weight in grams to three decimal places.
 */
export async function recordDispatch(
  orderId: string,
  ifMatch: string,
  input: DispatchInput,
): Promise<Dispatch> {
  const response = await transport.request<Dispatch, Record<string, unknown>>({
    method: "POST",
    path: `/gold-sale-orders/${orderId}/dispatches`,
    body: {
      dispatch_type: input.dispatchType,
      gold_weight: input.goldWeight ?? null,
      weight_unit: input.weightUnit ?? null,
      gold_purity: input.goldPurity ?? null,
      recipient_name: input.recipientName ?? null,
      dispatched_at: input.dispatchedAt ?? null,
      tracking_or_delivery_note: input.trackingOrDeliveryNote ?? null,
      evidence_file_id: input.evidenceFileId ?? null,
      guard_override_reason: input.guardOverrideReason ?? null,
    },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}

/** Where the order and its dispatch ended up. Both, because §8.2's edges move both rows. */
export type Closure = Readonly<{
  gold_sale_order_id: string;
  order_status: string;
  order_record_version: number;
  dispatch_id: string | null;
  dispatch_status: string | null;
  closed_at: string | null;
}>;

/**
 * Close the order.
 *
 * A different grant from dispatching — `gold_sale.review` rather than `gold_sale.dispatch` — so
 * the person who handed the gold over is not necessarily the person who declares the business
 * finished. The screen offers both and the server decides; §20.1.
 */
export async function closeOrder(
  orderId: string,
  ifMatch: string,
  closureNote?: string | null,
): Promise<Closure> {
  const response = await transport.request<Closure, { closure_note: string | null }>({
    method: "POST",
    path: `/gold-sale-orders/${orderId}/close`,
    body: { closure_note: closureNote ?? null },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}
