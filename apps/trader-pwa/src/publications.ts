/**
 * What happened to a payment, as its trader is told.
 * §9.9 (`15_Agent_Implementation_Plan.md:1256`), §9.10 (`:1273`), §9.11 (`:1277`).
 *
 * M11 Screens, slice 3. M9 published results, decided that a **failed** payment reaches its trader
 * as a notification rather than as a publication, and built the share file. No trader has ever
 * seen any of it.
 *
 * **The active publication only, and that is the contract's decision rather than this module's.**
 * §20.3: "Trader endpoints expose only own active publication and allowed historical correction
 * notices." `GET .../publication` returns one row; there is no trader-facing history route, so
 * this module cannot offer one. `publication_version` is what a trader learns instead — a version
 * above 1 means the centre corrected a result — and the gap is recorded rather than filled by
 * inventing a route.
 *
 * **`If-Match` is the request's version, not the publication's.** That is not obvious and it is
 * the whole reason `readRequest`'s `ETag` is threaded through this screen: an accountant may
 * correct a result while a trader is reading it, and the version that can go stale is the request
 * row the correction touches. The precondition is echoed from the server's `ETag`, never built
 * from `record_version` — `apps/admin-web/test/preconditions-come-from-the-server.test.ts` records
 * what happens when a screen computes one.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** A fresh key per attempt, so a retry of *this* click replays and a second click is second. */
function commandKey(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * One published result, exactly as the trader route publishes it.
 *
 * Deliberately narrower than the centre's `PublicationResponse`: no `primary_evidence_link_id` and
 * no `share_file_id`, because §20.3 gives the trader their own view and the extra ids identify
 * internal records. `summary_payload` is the redacted content the publication was built from.
 */
export type TraderPublication = Readonly<{
  id: string;
  payment_request_id: string;
  publication_version: number;
  status: string;
  request_status: string;
  content_hash: string;
  published_at: string;
  /** When this trader agreed the result was right. `null` until they do. */
  acknowledged_at: string | null;
  /** When this trader said it was wrong. `null` until they do. */
  disputed_at: string | null;
  summary_payload: Readonly<Record<string, unknown>>;
}>;

/**
 * Read the active publication for one of the caller's own requests.
 *
 * A 404 for a request that has no publication **and** for another trader's request, which is the
 * contract's choice and the right one: distinguishing them would confirm that somebody else's
 * request exists. `UI-PUB-001` asserts it from the server side.
 */
export async function readPublication(
  requestId: string,
  signal?: AbortSignal,
): Promise<TraderPublication> {
  const response = await transport.request<TraderPublication>({
    method: "GET",
    path: `/me/trader/payment-requests/${requestId}/publication`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * Agree that the published result is correct.
 *
 * **No body**, because agreeing needs no fields — the backend's own route says so. Both headers,
 * because `command_catalog.yaml` requires an idempotency key and the guard
 * `current_publication_identity_revalidated` requires the version.
 *
 * `ifMatch` is passed in rather than read here: it must be the `ETag` from the request read the
 * person was actually looking at, and a fresh read inside this function would defeat the
 * precondition by making it always current.
 */
export async function acknowledgeResult(
  requestId: string,
  ifMatch: string,
): Promise<TraderPublication> {
  const response = await transport.request<TraderPublication>({
    method: "POST",
    path: `/me/trader/payment-requests/${requestId}/acknowledge-result`,
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}

/**
 * The reasons a trader may give. The server validates `reason_code`, so this list exists to give
 * a person words rather than a free-text box — and a code the server refuses would be a 400 in
 * front of somebody reporting that their money did not arrive.
 */
export type DisputePayload = Readonly<{
  reason_code: string;
  description: string;
}>;

/**
 * Say the published result is wrong, and why.
 *
 * **This reverses nothing.** Doc 05: "A dispute creates a visible manual review task and does not
 * automatically reverse bank facts." The screen says so in as many words, because a button that
 * looks like an undo is worse than no button.
 */
export async function disputeResult(
  requestId: string,
  payload: DisputePayload,
  ifMatch: string,
): Promise<TraderPublication> {
  const response = await transport.request<TraderPublication, DisputePayload>({
    method: "POST",
    path: `/me/trader/payment-requests/${requestId}/dispute-result`,
    body: payload,
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}

/**
 * Where the result card for a publication is downloaded from.
 *
 * A path rather than a fetch: the file is a stream and the browser is better at saving one than
 * this module is. **Superseded publications remain downloadable** — §11.9 keeps old publications
 * so that what was shared stays accountable, and refusing the file would leave a document in the
 * world the platform denies producing. A trader can only reach the id of the *active* one through
 * the read above, which is a real limitation and is recorded in this module's docstring rather
 * than hidden.
 */
export function shareFilePath(publicationId: string): string {
  return `/api/v1/me/trader/publications/${publicationId}/share-file`;
}
