/**
 * The trader's own business, and nothing else.
 *
 * Per-app like `src/auth.ts`, and for the same reason: `UI-ISO-001` requires that this
 * bundle contain no admin endpoint path, and the cheapest guarantee is that it never
 * names one. This module knows exactly one path, and it is the caller's own.
 *
 * There is no id in the request. The business is chosen by the session's `trader_id`
 * server-side, which is what makes the ownership guarantee structural rather than a
 * filter this code could get wrong — `SEC-IDOR-001` is the test that proves it.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/**
 * What the platform shows a business about itself.
 *
 * Two status axes, not one, and the separation is load-bearing (DOC-CONFLICT-024):
 * `approval_status` is the centre's decision about the business, `operational_status` is
 * whether it may transact today. A suspended business is still an approved one.
 */
export type OwnTraderProfile = Readonly<{
  id: string;
  display_name: string;
  legal_name: string | null;
  primary_phone: string;
  operational_status: string;
  approval_status: string;
  record_version: number;
}>;

export async function readOwnProfile(signal?: AbortSignal): Promise<OwnTraderProfile> {
  const response = await transport.request<OwnTraderProfile>({
    method: "GET",
    path: "/me/trader/profile",
    ...(signal ? { signal } : {}),
  });
  return response.data;
}
