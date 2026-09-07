/**
 * What the bank did with a payment, and what the centre publishes about it.
 * §16.4 (`15_Agent_Implementation_Plan.md:1859`), §16.5 (`:1870`), §16.6 (`:1880`),
 * §16.7 (`:1894`), §16.8 (`:1900`).
 *
 * M11 Screens, slice 4. M9 built every command here and nothing has ever driven one from a
 * screen: results were confirmed by integration tests and published by nothing.
 *
 * **The read this module starts from did not exist before this slice.** All four attempt commands
 * require `If-Match` on the attempt, and no route in the contract returned an attempt's
 * `record_version` — `PaymentRequestDetail` says "`attempts` arrive with M6" and they did not, the
 * queue row is five fields by a disclosure decision, and `AttemptResult` was only ever a response
 * to a confirmation. `GET /payment-attempts/{id}` is the read those commands always presupposed.
 *
 * **Every precondition is the server's `ETag`, echoed.** Never `rv-${record_version}` built here:
 * `apps/admin-web/test/preconditions-come-from-the-server.test.ts` exists because a sabotage run
 * found a screen computing one, and the failure mode is a precondition that is present,
 * well-formed and meaningless.
 *
 * **No correction.** `payment_publication.correct` is granted to no role — POL-002 splits preparer
 * from approver and defers the split to ADR-SEC-009 — and `command_catalog.yaml` marks the command
 * `method: TBD, path: TBD`. A screen for it would be a surface nobody can open, which is the
 * defect this project has hit five times. Recorded in the plan, not built.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** A fresh key per attempt, so a retry of *this* click replays and a second click is second. */
function commandKey(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * One payment attempt, and what its request became.
 *
 * `request_status` is on the attempt response because a confirmation moves it: a screen that
 * re-read the request to find out would be reading a value another confirmation may already have
 * moved again.
 *
 * **No amount field is sent on any command below.** The attempt already knows what was sent, and
 * §17 `:1131`'s "amount is exact" is honoured by the absence rather than by a check — a
 * client-supplied figure could disagree with the row.
 */
export type PaymentAttempt = Readonly<{
  id: string;
  payment_request_id: string;
  attempt_number: number;
  status: string;
  amount_irr: number;
  bank_tracking_number: string | null;
  bank_result_at: string | null;
  failure_code: string | null;
  failure_reason: string | null;
  confirmed_at: string | null;
  record_version: number;
  request_status: string;
}>;

export type AttemptWithPrecondition = Readonly<{
  attempt: PaymentAttempt;
  /** The exact `ETag` the read returned, to be echoed as `If-Match`. */
  ifMatch: string;
}>;

export async function readAttempt(
  attemptId: string,
  signal?: AbortSignal,
): Promise<AttemptWithPrecondition> {
  const response = await transport.request<PaymentAttempt>({
    method: "GET",
    path: `/payment-attempts/${attemptId}`,
    ...(signal ? { signal } : {}),
  });
  if (!response.etag) {
    // Loud rather than silent. Without the ETag the next call would have to invent an `If-Match`,
    // and inventing one is how a confirmation lands on an attempt somebody else already moved.
    throw new Error("the read returned no ETag, so no command can be sent safely");
  }
  return { attempt: response.data, ifMatch: response.etag };
}

/**
 * Confirm that the bank paid.
 *
 * `bank_tracking_number` and `bank_result_at` are required by the contract — they are the bank's
 * own record of the movement, and a confirmation without them is an assertion with no source.
 *
 * **Evidence is either linked or its absence is explained.** `primary_evidence_link_id` and
 * `evidence_unavailable_reason` are both optional in the schema and the command's precondition is
 * `evidence_policy_satisfied`, so the screen offers one or the other rather than neither: a
 * confirmation with no evidence and no reason is the shape this policy exists to refuse.
 */
export type ConfirmPaidInput = Readonly<{
  bankTrackingNumber: string;
  bankResultAt: string;
  primaryEvidenceLinkId?: string | null;
  evidenceUnavailableReason?: string | null;
  confirmationNote?: string | null;
}>;

export async function confirmPaid(
  attemptId: string,
  ifMatch: string,
  input: ConfirmPaidInput,
): Promise<PaymentAttempt> {
  const response = await transport.request<PaymentAttempt, Record<string, unknown>>({
    method: "POST",
    path: `/payment-attempts/${attemptId}/confirm-paid`,
    body: {
      bank_tracking_number: input.bankTrackingNumber,
      bank_result_at: input.bankResultAt,
      primary_evidence_link_id: input.primaryEvidenceLinkId ?? null,
      evidence_unavailable_reason: input.evidenceUnavailableReason ?? null,
      confirmation_note: input.confirmationNote ?? null,
    },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}

/**
 * Confirm that the bank did not pay.
 *
 * Both fields are required, and `failure_code` is **not enumerated by this module**: the contract
 * types it as a plain string and no catalogue names a set. The same reasoning
 * `app/commands/trader_result.py` gives for a dispute reason applies — a closed list invented on a
 * screen becomes the closed list nobody approved. Here the audience is staff rather than a
 * customer, so the cost is lower, but the rule is the same and the list belongs in the catalogue.
 */
export type ConfirmFailedInput = Readonly<{
  failureCode: string;
  failureReason: string;
  receiptSegmentId?: string | null;
}>;

export async function confirmFailed(
  attemptId: string,
  ifMatch: string,
  input: ConfirmFailedInput,
): Promise<PaymentAttempt> {
  const response = await transport.request<PaymentAttempt, Record<string, unknown>>({
    method: "POST",
    path: `/payment-attempts/${attemptId}/confirm-failed`,
    body: {
      failure_code: input.failureCode,
      failure_reason: input.failureReason,
      receipt_segment_id: input.receiptSegmentId ?? null,
    },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}

/** Record that this attempt needs another one, without creating it. */
export async function markRetryRequired(
  attemptId: string,
  ifMatch: string,
  reason: string,
): Promise<PaymentAttempt> {
  const response = await transport.request<PaymentAttempt, { reason: string }>({
    method: "POST",
    path: `/payment-attempts/${attemptId}/mark-retry-required`,
    body: { reason },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}

/**
 * Create the next attempt.
 *
 * **`amount_irr` is required here and only here**, which looks like a contradiction of "no amount
 * on any command" and is not: a retry is a *new* attempt whose amount is a decision — the
 * unresolved remainder — rather than a restatement of what the bank already has. The confirmations
 * describe an existing movement; this one authorises a new one.
 */
export type CreateRetryInput = Readonly<{
  paymentRequestRevisionId: string;
  amountIrr: number;
  reason: string;
}>;

export async function createRetry(
  attemptId: string,
  ifMatch: string,
  input: CreateRetryInput,
): Promise<PaymentAttempt> {
  const response = await transport.request<PaymentAttempt, Record<string, unknown>>({
    method: "POST",
    path: `/payment-attempts/${attemptId}/retry`,
    body: {
      payment_request_revision_id: input.paymentRequestRevisionId,
      amount_irr: input.amountIrr,
      reason: input.reason,
    },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}

/** What a publication looks like to the centre, which sees more than its trader does. */
export type Publication = Readonly<{
  id: string;
  payment_request_id: string;
  publication_version: number;
  status: string;
  request_status: string;
  content_hash: string;
  published_at: string;
  primary_evidence_link_id: string | null;
  share_file_id: string | null;
  summary_payload: Readonly<Record<string, unknown>>;
}>;

/**
 * What publishing *would* say, without publishing it.
 *
 * **No idempotency key and no precondition**, because the route requires neither: the preview
 * creates nothing to replay. It does move the request to `result_ready_for_trader`, which running
 * twice leaves where running once did.
 */
export type PublicationPreview = Readonly<{
  payment_request_id: string;
  request_status: string;
  next_publication_version: number;
  content_hash: string;
  summary_payload: Readonly<Record<string, unknown>>;
}>;

export async function previewPublication(
  requestId: string,
  primaryEvidenceLinkId?: string | null,
): Promise<PublicationPreview> {
  const response = await transport.request<
    PublicationPreview,
    { primary_evidence_link_id: string | null }
  >({
    method: "POST",
    path: `/payment-requests/${requestId}/publications/preview`,
    body: { primary_evidence_link_id: primaryEvidenceLinkId ?? null },
  });
  return response.data;
}

/**
 * Publish the result to its trader.
 *
 * **`If-Match` is the request's version, not the publication's**, and the backend's own note says
 * why: a publication has no prior version to be stale against, but the *request* does — an
 * accountant who read it, went to make tea, and published while somebody else corrected the result
 * would publish a snapshot of something that had moved.
 *
 * **No step-up.** `UI-RESULT-001`'s first wording asked for the recent-auth dialog here;
 * `command_catalog.yaml` carries no `recent_auth` field on `payment_publication.publish` and
 * carries `required_for_approving_second_human` on the *correction*. Sending `X-Recent-Auth`
 * anyway would be a screen inventing a control, and asking a person to reauthenticate for a
 * command that does not require it trains them to type their password on request.
 */
export async function publishResult(
  requestId: string,
  ifMatch: string,
  input: Readonly<{ messageToTrader?: string | null; primaryEvidenceLinkId?: string | null }> = {},
): Promise<Publication> {
  const response = await transport.request<Publication, Record<string, unknown>>({
    method: "POST",
    path: `/payment-requests/${requestId}/publications`,
    body: {
      message_to_trader: input.messageToTrader ?? null,
      primary_evidence_link_id: input.primaryEvidenceLinkId ?? null,
    },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}

/**
 * Every publication for a request, superseded ones included.
 *
 * **The history is the centre's**, §20.3: "Internal users see history subject to permission.
 * Trader endpoints expose only own active publication." Guarded by
 * `payment_publication.preview` rather than `.publish`, because reading what was published is
 * weaker than publishing it.
 *
 * **A bare array, not an envelope.** Read from the published contract rather than assumed: this
 * route answers `PublicationResponse[]` directly, where every other list surface in this
 * application returns `{ items, next_cursor, total }`. The first draft of this module typed it as
 * an envelope, which would have rendered an empty history for every request — silently, because
 * `body.items` on an array is simply `undefined`.
 */
export async function listPublications(
  requestId: string,
  signal?: AbortSignal,
): Promise<readonly Publication[]> {
  const response = await transport.request<readonly Publication[]>({
    method: "GET",
    path: `/payment-requests/${requestId}/publications`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}
