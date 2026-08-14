/**
 * Staff account administration from a screen, which slice 8E built ten routes for and none.
 *
 * Per-app like `src/traders.ts` and for the same reason: `UI-ISO-001` requires that neither
 * bundle name the other's endpoint paths, and there is no trader-side equivalent of this
 * module and must not be.
 *
 * **Every precondition comes from the server.** `readAdminUser` returns the `ETag` the
 * backend published and each write echoes it unchanged. A screen computing `rv-${n}` itself
 * would be inventing a precondition, and the first time the two spellings disagreed the
 * change would land on an account somebody else had already amended.
 *
 * **The password is never returned and never stored.** Creation sends one and gets an
 * account back with no credential in it; the reset sends one and gets a status back. This
 * module holds neither beyond the call — `API-PWD-002` is a claim about the server, and a
 * client that cached what it sent would make the claim untrue at the other end.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

export type AdminUser = Readonly<{
  id: string;
  username: string;
  full_name: string;
  email: string | null;
  phone_number: string | null;
  status: string;
  role_codes: readonly string[];
  record_version: number;
}>;

export type AdminUserWithPrecondition = Readonly<{
  account: AdminUser;
  /** The exact `ETag` the read returned, to be echoed as `If-Match`. */
  ifMatch: string;
}>;

export type NewAdminUser = Readonly<{
  username: string;
  fullName: string;
  password: string;
  roleCodes: readonly string[];
  email?: string | undefined;
  phoneNumber?: string | undefined;
}>;

/** What a change to somebody else's account answers with. Never a credential. */
export type StateChange = Readonly<{
  id: string;
  status: string;
  record_version: number;
  sessions_revoked: number;
}>;

export async function listAdminUsers(signal?: AbortSignal): Promise<readonly AdminUser[]> {
  const response = await transport.request<{ admin_users: readonly AdminUser[] }>({
    method: "GET",
    path: "/admin-users",
    ...(signal ? { signal } : {}),
  });
  return response.data.admin_users;
}

export async function readAdminUser(
  id: string,
  signal?: AbortSignal,
): Promise<AdminUserWithPrecondition> {
  const response = await transport.request<AdminUser>({
    method: "GET",
    path: `/admin-users/${id}`,
    ...(signal ? { signal } : {}),
  });
  if (!response.etag) {
    throw new Error("the read returned no ETag, so no change can be made safely");
  }
  return { account: response.data, ifMatch: response.etag };
}

/**
 * A fresh key per creation.
 *
 * The server resolves and persists this one — `admin_user_lifecycle.py` claims through
 * `IdempotencyResolver` rather than requiring the header and discarding it — so a retried
 * submit returns the first account instead of a second person with the same name.
 */
function creationKey(): string {
  return globalThis.crypto.randomUUID();
}

export async function createAdminUser(
  input: NewAdminUser,
  signal?: AbortSignal,
): Promise<AdminUser> {
  const response = await transport.request<AdminUser>({
    method: "POST",
    path: "/admin-users",
    body: {
      username: input.username,
      full_name: input.fullName,
      password: input.password,
      role_codes: [...input.roleCodes],
      ...(input.email ? { email: input.email } : {}),
      ...(input.phoneNumber ? { phone_number: input.phoneNumber } : {}),
    },
    idempotencyKey: creationKey(),
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * Suspend or reactivate. `reason` is mandatory for the first and refused for neither.
 *
 * The server requires a reason to suspend and not to reactivate — an access removal nobody
 * explained cannot be reviewed later, while restoring access needs no defence. Mirrored
 * here so the screen asks for what will be required rather than discovering it in a 400.
 */
export async function changeAdminUserState(
  id: string,
  action: "suspend" | "reactivate",
  ifMatch: string,
  reason: string | undefined,
  signal?: AbortSignal,
): Promise<StateChange> {
  const response = await transport.request<StateChange, { reason?: string }>({
    method: "POST",
    path: `/admin-users/${id}/${action}`,
    body: reason === undefined ? {} : { reason },
    ifMatch,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * Set another administrator's credential.
 *
 * The password is chosen by the caller and communicated out of band — nothing is generated
 * and nothing comes back. The account lands in `recovery_required` and its owner completes
 * the recovery, which is the only transition out of that state.
 */
export async function resetAdminUserPassword(
  id: string,
  ifMatch: string,
  newPassword: string,
  reason: string,
  signal?: AbortSignal,
): Promise<StateChange> {
  const response = await transport.request<
    StateChange,
    { new_password: string; reason: string }
  >({
    method: "POST",
    path: `/admin-users/${id}/password-reset`,
    body: { new_password: newPassword, reason },
    ifMatch,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

export type Role = Readonly<{
  id: string;
  code: string;
  description: string | null;
  is_system: boolean;
  is_enabled: boolean;
  permission_codes: readonly string[];
}>;

export async function listRoles(signal?: AbortSignal): Promise<readonly Role[]> {
  const response = await transport.request<{ roles: readonly Role[] }>({
    method: "GET",
    path: "/roles",
    ...(signal ? { signal } : {}),
  });
  return response.data.roles;
}
