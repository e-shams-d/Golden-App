/**
 * Confirming that the gold arrived.
 * `06_Workflows_and_State_Machines.md` §8.2's `dispatched --> received_by_trader`.
 *
 * M11 Screens, slice 7. M10 built this and no trader has ever acknowledged a delivery.
 *
 * **One route, and the trader's own.** It is guarded by ownership rather than a permission — a
 * trader session resolves no grants at all, and the thing being asserted is that the gold arrived
 * at *their* business. `owned_or_permitted` carries the permission name for the classification
 * gate to see while ownership does the work.
 *
 * **`If-Match` is the order's, not the dispatch's**, which the route's own note explains: §8.2
 * moves both rows and the order is the aggregate. `readOrder` in `src/gold-orders.ts` issues that
 * `ETag`, so this module needs no read of its own — the precondition gate slice 5 built confirmed
 * as much before this screen was written.
 *
 * Separate from the centre's `dispatch.ts` per `UI-ISO-001`: that one names `/dispatches` and
 * `/close`, neither of which a trader may call.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

function commandKey(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * One dispatch recorded against an order.
 *
 * **Read as a list, not as a `current_dispatch_id` on the order.** `gold_dispatches` carries
 * `superseded` and `cancelled` among its six statuses and has no unique constraint per order, so
 * "the current one" is a concept the backend does not define — inventing it in a response would
 * promote a screen's guess to a contract. The trader acknowledges the one that is `dispatched`;
 * a superseded one stays visible, the same reason the match list keeps rejected candidates.
 */
export type Dispatch = Readonly<{
  id: string;
  gold_sale_order_id: string;
  dispatch_type: string;
  status: string;
  gold_weight: string | null;
  weight_unit: string | null;
  dispatched_at: string | null;
  order_status: string;
  record_version: number;
  created_at: string;
}>;

/** Every dispatch against this order, oldest first — the sequence of movements forwards. */
export async function listDispatches(
  orderId: string,
  signal?: AbortSignal,
): Promise<readonly Dispatch[]> {
  const response = await transport.request<readonly Dispatch[]>({
    method: "GET",
    path: `/gold-sale-orders/${orderId}/dispatches`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/** Where the order and its dispatch ended up after the acknowledgement. */
export type Closure = Readonly<{
  gold_sale_order_id: string;
  order_status: string;
  order_record_version: number;
  dispatch_id: string | null;
  dispatch_status: string | null;
  closed_at: string | null;
}>;

/**
 * Say the gold arrived.
 *
 * **No body.** Confirming receipt needs no fields — the trader is agreeing with what the centre
 * recorded, and a form would invite them to restate a weight the warehouse already wrote down.
 * Disagreeing is not this route: that is a conversation, and inventing a dispute surface here
 * would be building a workflow nobody has specified.
 */
export async function acknowledgeDispatch(
  orderId: string,
  dispatchId: string,
  ifMatch: string,
): Promise<Closure> {
  const response = await transport.request<Closure>({
    method: "POST",
    path: `/gold-sale-orders/${orderId}/dispatches/${dispatchId}/acknowledge`,
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}
