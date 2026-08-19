/**
 * The trader's own requests: listing them, opening one, correcting one, sending it.
 *
 * Per-app rather than shared, for the reason `src/auth.ts` gives: `UI-ISO-001` requires that
 * neither bundle contain the other's endpoint paths, and the cheapest guarantee is that
 * neither bundle ever names one. The admin app has its own module and must.
 *
 * **No arithmetic on money anywhere in this file.** `15_Agent_Implementation_Plan.md:802`
 * makes the server authoritative for the conversion, and `MONEY_TIME_CONTRACT` rule 8 keeps
 * every monetary value a string on the wire. So `amountPayload` passes the typed digits and
 * the chosen unit through untouched: a browser that multiplied by ten would be a second
 * implementation of the conversion, and the first time the two disagreed the trader would
 * have authorised an amount they never typed.
 *
 * `amountPayload` is exported for exactly that reason — it is the one place a conversion
 * could hide, so it is the one place a test can watch.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** The units the backend accepts. Not a free string: a typo would be a silent rejection. */
export type AmountUnit = "IRR" | "TOMAN";

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
  /** What the accountant told this trader when they returned it. `UI-REQ-001` renders it. */
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
  /** Which commands the server says are available. Advisory: the 403 still refuses. */
  allowed_actions: readonly string[];
}>;

export type DetailWithPrecondition = Readonly<{
  detail: RequestDetail;
  /** The exact `ETag` the read returned, to be echoed as `If-Match`. */
  ifMatch: string;
}>;

/**
 * What goes on the wire for an amount: the digits as typed, and the unit as chosen.
 *
 * The value is a string, not a number. `MONEY_TIME_CONTRACT` rule 8 requires it, and the
 * reason is arithmetic: IRR amounts in this business exceed `Number.MAX_SAFE_INTEGER`
 * territory quickly enough that a JSON number would start rounding a settlement.
 */
export function amountPayload(value: string, unit: AmountUnit): EnteredAmount {
  return { value, unit };
}

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
    // Loud rather than silent, as `admin-web/src/traders.ts` puts it: without the ETag the
    // next call would have to invent an `If-Match`, and inventing one is how a correction
    // lands on a revision somebody else already replaced.
    throw new Error("the read returned no ETag, so no command can be sent safely");
  }
  return { detail: response.data, ifMatch: response.etag };
}

export type RevisionHistory = Readonly<{
  items: readonly Revision[];
  current_revision_id: string | null;
}>;

/**
 * Every revision, oldest first, with the current one named separately.
 *
 * The order is the backend's — by `revision_number`, not by timestamp, because two revisions
 * written in the same second would otherwise read in an order nobody chose. `UI-REQ-002`
 * renders this and distinguishes the current one.
 */
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

/** A fresh key per attempt, so a retry of *this* click replays and a second click is second. */
function commandKey(): string {
  return globalThis.crypto.randomUUID();
}

export async function createDraft(
  input: Readonly<{
    beneficiaryId: string;
    value: string;
    unit: AmountUnit;
    description: string | null;
  }>,
  signal?: AbortSignal,
): Promise<{ request: PaymentRequest; revision: Revision }> {
  const response = await transport.request<
    { request: PaymentRequest; revision: Revision },
    {
      beneficiary_id: string;
      amount: EnteredAmount;
      description: string | null;
    }
  >({
    method: "POST",
    path: "/payment-requests",
    body: {
      beneficiary_id: input.beneficiaryId,
      amount: amountPayload(input.value, input.unit),
      description: input.description,
    },
    idempotencyKey: commandKey(),
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

export async function createRevision(
  requestId: string,
  ifMatch: string,
  input: Readonly<{
    beneficiaryId: string;
    value: string;
    unit: AmountUnit;
    description: string | null;
    revisionReason: string | null;
  }>,
  signal?: AbortSignal,
): Promise<{ request: PaymentRequest; revision: Revision }> {
  const response = await transport.request<
    { request: PaymentRequest; revision: Revision },
    {
      beneficiary_id: string;
      amount: EnteredAmount;
      description: string | null;
      revision_reason: string | null;
    }
  >({
    method: "POST",
    path: `/payment-requests/${requestId}/revisions`,
    body: {
      beneficiary_id: input.beneficiaryId,
      amount: amountPayload(input.value, input.unit),
      description: input.description,
      revision_reason: input.revisionReason,
    },
    idempotencyKey: commandKey(),
    ifMatch,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

export async function submitRequest(
  requestId: string,
  ifMatch: string,
  signal?: AbortSignal,
): Promise<PaymentRequest> {
  const response = await transport.request<PaymentRequest, Record<string, never>>({
    method: "POST",
    path: `/payment-requests/${requestId}/submit`,
    body: {},
    idempotencyKey: commandKey(),
    ifMatch,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

export async function cancelRequest(
  requestId: string,
  ifMatch: string,
  reason: string | null,
  signal?: AbortSignal,
): Promise<PaymentRequest> {
  const response = await transport.request<PaymentRequest, { reason?: string }>({
    method: "POST",
    path: `/payment-requests/${requestId}/cancel`,
    body: reason === null ? {} : { reason },
    idempotencyKey: commandKey(),
    ifMatch,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * Field names mirror the published contract exactly, and both of these were guessed wrong
 * on the first attempt — `beneficiaries` for what the contract calls `items`, and
 * `warnings` for `duplicate_warnings`. Read from `openapi/v1.json` rather than remembered,
 * because a wrong key here is `undefined` at runtime and an empty screen with no error.
 */
export type Beneficiary = Readonly<{
  id: string;
  full_name: string;
  iban: string;
  status: string;
  verification_status: string;
  record_version: number;
}>;

/** Slice 2's non-blocking warning: it names what matched, and does not refuse. */
export type DuplicateWarning = Readonly<{
  beneficiary_id: string;
  full_name: string;
  matched_on: string;
}>;

export async function listBeneficiaries(signal?: AbortSignal): Promise<readonly Beneficiary[]> {
  const response = await transport.request<{ items: readonly Beneficiary[] }>({
    method: "GET",
    path: "/beneficiaries",
    ...(signal ? { signal } : {}),
  });
  return response.data.items;
}

export async function createBeneficiary(
  input: Readonly<{ fullName: string; iban: string; nationalId: string | null }>,
  signal?: AbortSignal,
): Promise<{
  beneficiary: Beneficiary;
  duplicate_warnings: readonly DuplicateWarning[];
}> {
  const response = await transport.request<
    { beneficiary: Beneficiary; duplicate_warnings: readonly DuplicateWarning[] },
    { full_name: string; iban: string; national_id: string | null }
  >({
    method: "POST",
    path: "/beneficiaries",
    body: { full_name: input.fullName, iban: input.iban, national_id: input.nationalId },
    idempotencyKey: commandKey(),
    ...(signal ? { signal } : {}),
  });
  return response.data;
}
