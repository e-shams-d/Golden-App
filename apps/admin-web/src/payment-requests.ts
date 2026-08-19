/**
 * The centre's view of a payment request, and the three decisions an accountant makes.
 *
 * Per-app rather than shared with the trader bundle, for the reason `src/traders.ts` gives:
 * `UI-ISO-001` requires that neither bundle contain the other's endpoint paths, and the
 * cheapest guarantee is that neither bundle ever names one. The overlap with the trader
 * module is the two reads, and duplicating those is the price of that guarantee.
 *
 * **`If-Match` always comes from a read, never from arithmetic.** `readRequest` returns the
 * `ETag` the backend published and every command echoes it unchanged. A screen that computed
 * `rv-${record_version}` itself would be inventing a precondition, and the first time the two
 * spellings disagreed a decision would land on a request somebody else had already moved.
 *
 * **No money arithmetic here either.** The amounts arrive as strings and are rendered as
 * strings; this side never converts, because there is nothing for it to convert — the
 * accountant reads what the trader typed and what the server derived.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

export type EnteredAmount = Readonly<{ value: string; unit: string }>;

export type Revision = Readonly<{
  id: string;
  revision_number: number;
  beneficiary_name_snapshot: string;
  beneficiary_iban_snapshot: string;
  amount_irr: string;
  entered_amount: EnteredAmount | null;
  description: string | null;
  content_hash: string;
}>;

export type PaymentRequest = Readonly<{
  id: string;
  trader_id: string;
  beneficiary_id: string;
  request_number: string;
  status: string;
  current_revision_id: string | null;
  review_note: string | null;
  reviewed_at: string | null;
  record_version: number;
}>;

export type RequestListing = Readonly<{
  request: PaymentRequest;
  current_revision: Revision | null;
}>;

export type RequestDetail = Readonly<{
  request: PaymentRequest;
  current_revision: Revision | null;
  /** What the server says is available. Advisory: the command still refuses. */
  allowed_actions: readonly string[];
}>;

export type DetailWithPrecondition = Readonly<{
  detail: RequestDetail;
  ifMatch: string;
}>;

export type RevisionHistory = Readonly<{
  items: readonly Revision[];
  current_revision_id: string | null;
}>;

export async function listRequests(
  status?: string,
  signal?: AbortSignal,
): Promise<readonly RequestListing[]> {
  const response = await transport.request<{ items: readonly RequestListing[] }>({
    method: "GET",
    path: status ? `/payment-requests?status=${encodeURIComponent(status)}` : "/payment-requests",
    ...(signal ? { signal } : {}),
  });
  return response.data.items;
}

export async function readRequest(
  requestId: string,
  signal?: AbortSignal,
): Promise<DetailWithPrecondition> {
  const response = await transport.request<RequestDetail>({
    method: "GET",
    path: `/payment-requests/${requestId}`,
    ...(signal ? { signal } : {}),
  });
  if (!response.etag) {
    throw new Error("the read returned no ETag, so no decision can be made safely");
  }
  return { detail: response.data, ifMatch: response.etag };
}

export async function listRevisions(
  requestId: string,
  signal?: AbortSignal,
): Promise<RevisionHistory> {
  const response = await transport.request<RevisionHistory>({
    method: "GET",
    path: `/payment-requests/${requestId}/revisions`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/** A fresh key per decision, so a retry of *this* click replays and a second click is second. */
function decisionKey(): string {
  return globalThis.crypto.randomUUID();
}

export async function startReview(
  requestId: string,
  ifMatch: string,
  signal?: AbortSignal,
): Promise<PaymentRequest> {
  const response = await transport.request<PaymentRequest, Record<string, never>>({
    method: "POST",
    path: `/payment-requests/${requestId}/start-review`,
    body: {},
    idempotencyKey: decisionKey(),
    ifMatch,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * Both `reason_code` and `message_to_trader` are required parameters, not optional ones.
 *
 * `05_API_Specification.md:1211` says "Reason and trader notification are required", and the
 * message is what the trader's correction screen renders — a return with no message is a
 * request whose owner has no idea what to change.
 */
export async function requestCorrection(
  requestId: string,
  ifMatch: string,
  input: Readonly<{ reasonCode: string; messageToTrader: string; internalNote: string | null }>,
  signal?: AbortSignal,
): Promise<PaymentRequest> {
  const response = await transport.request<
    PaymentRequest,
    { reason_code: string; message_to_trader: string; internal_note: string | null }
  >({
    method: "POST",
    path: `/payment-requests/${requestId}/request-correction`,
    body: {
      reason_code: input.reasonCode,
      message_to_trader: input.messageToTrader,
      internal_note: input.internalNote,
    },
    idempotencyKey: decisionKey(),
    ifMatch,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * `expectedRevisionId` is the guard document 06 `:644` calls "current revision valid".
 *
 * The accountant states which revision they validated. If a correction landed while they were
 * reading, the command fails rather than marking a revision nobody approved as eligible — so
 * the id comes from the read that populated the screen, not from a later refresh.
 */
export async function markEligible(
  requestId: string,
  ifMatch: string,
  input: Readonly<{ expectedRevisionId: string; reviewNote: string | null }>,
  signal?: AbortSignal,
): Promise<PaymentRequest> {
  const response = await transport.request<
    PaymentRequest,
    { expected_revision_id: string; review_note: string | null }
  >({
    method: "POST",
    path: `/payment-requests/${requestId}/mark-eligible-for-batching`,
    body: {
      expected_revision_id: input.expectedRevisionId,
      review_note: input.reviewNote,
    },
    idempotencyKey: decisionKey(),
    ifMatch,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}
