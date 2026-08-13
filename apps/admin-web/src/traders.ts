/**
 * The centre's view of the businesses it approves, and the two decisions a screen makes.
 *
 * Per-app for the same reason `src/auth.ts` is: `UI-ISO-001` requires that neither bundle
 * contain the other's endpoint paths, and the cheapest guarantee is that neither bundle
 * ever names one. There is no trader-side equivalent of this module and there must not be.
 *
 * **The `If-Match` comes from the server, never from arithmetic.** `readTrader` returns the
 * `ETag` the backend published, and `approve`/`reject` send it back unchanged. A screen
 * that computed `rv-${record_version}` itself would be inventing a precondition, and the
 * first time the two spellings disagreed the decision would land on a business somebody
 * else had already changed.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** What the centre may see of a business. Mirrors the published contract. */
export type Trader = Readonly<{
  id: string;
  display_name: string;
  legal_name: string | null;
  primary_phone: string;
  operational_status: string;
  approval_status: string;
  approved_at: string | null;
  record_version: number;
}>;

export type TraderWithPrecondition = Readonly<{
  trader: Trader;
  /** The exact `ETag` the read returned, to be echoed as `If-Match`. */
  ifMatch: string;
}>;

export async function listTraders(signal?: AbortSignal): Promise<readonly Trader[]> {
  const response = await transport.request<{ traders: readonly Trader[] }>({
    method: "GET",
    path: "/traders",
    ...(signal ? { signal } : {}),
  });
  return response.data.traders;
}

export async function readTrader(
  traderId: string,
  signal?: AbortSignal,
): Promise<TraderWithPrecondition> {
  const response = await transport.request<Trader>({
    method: "GET",
    path: `/traders/${traderId}`,
    ...(signal ? { signal } : {}),
  });
  if (!response.etag) {
    // Loud rather than silent. Without the ETag the next call would have to invent an
    // `If-Match`, and inventing one is how a decision lands on a stale record.
    throw new Error("the read returned no ETag, so no decision can be made safely");
  }
  return { trader: response.data, ifMatch: response.etag };
}

/**
 * A fresh key per decision, so a retry of *this* click is a replay and a second click is
 * a second decision.
 *
 * `crypto.randomUUID` rather than a counter or a timestamp: two operators acting at the
 * same moment must not collide, and a key derived from the trader id would make an
 * intended second decision look like a retry of the first.
 */
function decisionKey(): string {
  return globalThis.crypto.randomUUID();
}

async function decide(
  traderId: string,
  action: "approve" | "reject",
  ifMatch: string,
  reason: string | undefined,
  signal?: AbortSignal,
): Promise<Trader> {
  const response = await transport.request<Trader, { reason?: string }>({
    method: "POST",
    path: `/traders/${traderId}/${action}`,
    body: reason === undefined ? {} : { reason },
    idempotencyKey: decisionKey(),
    ifMatch,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

export async function approveTrader(
  traderId: string,
  ifMatch: string,
  signal?: AbortSignal,
): Promise<Trader> {
  return decide(traderId, "approve", ifMatch, undefined, signal);
}

/** `reason` is mandatory server-side (`05_API_Specification.md:894-895`), so it is required here. */
export async function rejectTrader(
  traderId: string,
  ifMatch: string,
  reason: string,
  signal?: AbortSignal,
): Promise<Trader> {
  return decide(traderId, "reject", ifMatch, reason, signal);
}
