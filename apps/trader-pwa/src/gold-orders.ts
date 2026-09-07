/**
 * Buying gold from the centre, as the trader files it.
 * §9.12 (`15_Agent_Implementation_Plan.md:1287`), §17.1 (`:1931`).
 *
 * M11 Screens, slice 5. M10 built this aggregate and no trader has ever created an order.
 *
 * **Two apps, two modules, one route** — the second time after notifications. `UI-ISO-001` is
 * about neither bundle carrying the other's endpoint paths, and `/gold-sale-orders` is reached by
 * both audiences under different guards: `owned_or_permitted("gold_sale.create_own",
 * "gold_sale.review")` means a trader passes on ownership and the centre on a grant. A shared
 * module would put the centre's pricing path in this bundle the first time somebody added a
 * helper to it.
 *
 * **The `ETag` is what `submit` requires, and it did not exist until this slice.**
 * `GET /gold-sale-orders/{id}` returned `record_version` in the body and no header, so the only
 * way to satisfy the precondition was to compute it. `tests/backend/test_preconditions_have_a_
 * source.py` now asks that of every command in the contract, because the same absence turned up
 * in three unrelated routers at once.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** A fresh key per attempt, so a retry of *this* click replays and a second click is second. */
function commandKey(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * One order, exactly as the contract publishes it.
 *
 * **`gold_weight` is a string and stays one.** A weight in grams to three decimal places is not
 * safe as a JSON number, and the same reasoning `MONEY_TIME_CONTRACT` rule 8 gives for amounts
 * applies: parsing it here to render it would introduce the rounding the string exists to avoid.
 *
 * `expected_amount_irr` is `null` until the centre prices the order — absent rather than zero,
 * because zero is a price and "not yet priced" is not.
 */
export type GoldOrder = Readonly<{
  id: string;
  order_number: string;
  trader_id: string;
  status: string;
  gold_type: string;
  gold_weight: string;
  weight_unit: string;
  gold_purity: string;
  expected_amount_irr: number | null;
  final_amount_irr: number | null;
  current_pricing_version_id: string | null;
  record_version: number;
  created_at: string;
}>;

export type OrderWithPrecondition = Readonly<{
  order: GoldOrder;
  /** The exact `ETag` the read returned, to be echoed as `If-Match`. */
  ifMatch: string;
}>;

/**
 * The caller's own orders.
 *
 * A bare array, not an envelope — read from the published contract rather than assumed, which is
 * the mistake slice 4 made with the publication history and caught by typing it against the
 * contract.
 */
export async function listOrders(signal?: AbortSignal): Promise<readonly GoldOrder[]> {
  const response = await transport.request<readonly GoldOrder[]>({
    method: "GET",
    path: "/gold-sale-orders",
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

export async function readOrder(
  orderId: string,
  signal?: AbortSignal,
): Promise<OrderWithPrecondition> {
  const response = await transport.request<GoldOrder>({
    method: "GET",
    path: `/gold-sale-orders/${orderId}`,
    ...(signal ? { signal } : {}),
  });
  if (!response.etag) {
    // Loud rather than silent. Without the ETag the submit below would have to invent an
    // `If-Match`, and an invented precondition compares a state nobody observed.
    throw new Error("the read returned no ETag, so no command can be sent safely");
  }
  return { order: response.data, ifMatch: response.etag };
}

export type CreateOrderInput = Readonly<{
  goldType: string;
  goldWeight: string;
  weightUnit: string;
  goldPurity: string;
}>;

/**
 * File a new order.
 *
 * **No `If-Match`**, and the contract agrees: there is no prior version of a row that does not
 * exist yet. `Idempotency-Key` is still required — a double-submitted form must not become two
 * orders for the same gold.
 *
 * The weight is sent as the string the person typed. The contract accepts a number too; sending
 * the string keeps the value they entered rather than one JavaScript rounded on the way past.
 */
export async function createOrder(input: CreateOrderInput): Promise<GoldOrder> {
  const response = await transport.request<GoldOrder, Record<string, unknown>>({
    method: "POST",
    path: "/gold-sale-orders",
    body: {
      gold_type: input.goldType,
      gold_weight: input.goldWeight,
      weight_unit: input.weightUnit,
      gold_purity: input.goldPurity,
    },
    idempotencyKey: commandKey(),
  });
  return response.data;
}

/**
 * Hand the order to the centre.
 *
 * `ifMatch` is passed in rather than read here: it must be the `ETag` from the read the person was
 * actually looking at. A fresh read inside this function would make the precondition always
 * current, which is the defect slice 3 recorded — the guard exists to catch a change that happened
 * while somebody was reading.
 */
export async function submitOrder(orderId: string, ifMatch: string): Promise<GoldOrder> {
  const response = await transport.request<GoldOrder>({
    method: "POST",
    path: `/gold-sale-orders/${orderId}/submit`,
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}
