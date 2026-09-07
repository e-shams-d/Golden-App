/**
 * The centre's side of a gold order: read it, and price it.
 * §17.2 (`15_Agent_Implementation_Plan.md:1944`).
 *
 * M11 Screens, slice 5. M10 built the pricing command and nothing has ever priced an order.
 *
 * **A separate module from the trader's, per `UI-ISO-001`**, and here the rule earns its keep more
 * than usual: this module names `/pricing-versions`, a path guarded by `gold_sale.price` — a grant
 * no trader can hold. A shared module would ship that path into the trader bundle, where the only
 * thing standing between a curious person and the pricing surface would be the server's 403. The
 * server would refuse; the point is that the path should not be there to try.
 *
 * **The `ETag` the pricing command needs did not exist until this slice.** `GET
 * /gold-sale-orders/{id}` returned `record_version` in the body with no header. See
 * `tests/backend/test_preconditions_have_a_source.py`, which now asks that of the whole contract.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** A fresh key per attempt, so a retry of *this* click replays and a second click is second. */
function commandKey(): string {
  return globalThis.crypto.randomUUID();
}

/** One order as the centre sees it. The same shape the trader gets — §20.3 draws no line here. */
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
  ifMatch: string;
}>;

/**
 * One pricing version.
 *
 * **Immutable and numbered**, with `superseded_at` naming the moment a later one replaced it. A
 * screen shows the current one and the ones before it; nothing edits a version, which is why the
 * command below *creates* rather than updates.
 *
 * `content_hash` is what makes a price checkable against what was agreed — the same role it plays
 * on a publication.
 */
export type PricingVersion = Readonly<{
  id: string;
  version_number: number;
  pricing_method: string;
  gold_weight: string;
  weight_unit: string;
  gold_purity: string;
  unit_price_irr: number;
  expected_amount_irr: number;
  content_hash: string;
  created_at: string;
  superseded_at: string | null;
}>;

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
    throw new Error("the read returned no ETag, so no command can be sent safely");
  }
  return { order: response.data, ifMatch: response.etag };
}

export type PricingInput = Readonly<{
  unitPriceIrr: number;
  /**
   * What the accountant typed, if they entered a total rather than a unit price.
   *
   * Both are optional in the contract and neither is derived here: the server computes
   * `expected_amount_irr` from the weight and the unit price, and a second calculation in this
   * module would be a number that agrees today and disagrees the first time rounding changes.
   */
  enteredAmountValue?: number | null;
  enteredAmountUnit?: string | null;
  pricingNote?: string | null;
}>;

/**
 * Price the order, creating version N+1.
 *
 * **`If-Match` is the order's version, and this is `UI-GOLD-001`'s whole claim.** Two accountants
 * pricing the same order is the ordinary case, not an edge one: the first creates version 1 and
 * moves the order, so the second — holding the version they read a minute ago — is refused rather
 * than silently superseding a price somebody has already quoted.
 *
 * The `ETag` comes from `readOrder`, echoed. Never computed from `record_version`.
 */
export async function createPricingVersion(
  orderId: string,
  ifMatch: string,
  input: PricingInput,
): Promise<PricingVersion> {
  const response = await transport.request<PricingVersion, Record<string, unknown>>({
    method: "POST",
    path: `/gold-sale-orders/${orderId}/pricing-versions`,
    body: {
      unit_price_irr: input.unitPriceIrr,
      entered_amount_value: input.enteredAmountValue ?? null,
      entered_amount_unit: input.enteredAmountUnit ?? null,
      pricing_note: input.pricingNote ?? null,
    },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}
