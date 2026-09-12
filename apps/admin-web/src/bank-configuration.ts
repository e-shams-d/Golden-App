/**
 * Bank configuration: the profiles, their versions, and the accounts money leaves from.
 *
 * M0 slice B. Every operation here has existed since M2 or M4 and **none of them had a screen** —
 * a bank that changed a transfer limit or a cutoff time could not be recorded by anybody.
 *
 * **The version read is the reason this slice needed a backend change.** `GET /bank-profiles`
 * answers four fields and no versions, and `POST /bank-profiles` answers with the id of the
 * version it has just created. So the only `version_id` obtainable anywhere was one the caller had
 * personally made moments earlier, and activating an *existing* configuration — the whole point of
 * the command — could not be reached from a screen at all. `GET /bank-profiles/{id}` is that read.
 *
 * **Monetary values are strings on the wire.** `MONEY_TIME_CONTRACT.md:17` makes base-10 integer
 * strings the format and rule 9 forbids JavaScript `Number` for them. They are carried as strings
 * here and rendered as strings; nothing in this module parses one.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

// Its own transport, like every other data module here. One shared instance would be a singleton
// holding a CSRF reader, and `admin-users.ts` set the pattern this follows.
const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** A bank, as the list shows it. Four fields, which is all that route returns. */
export type BankProfileSummary = Readonly<{
  id: string;
  code: string;
  name: string;
  status: string;
}>;

/** One immutable configuration snapshot. */
export type BankProfileVersion = Readonly<{
  id: string;
  version_number: number;
  status: string;
  effective_from: string | null;
  effective_to: string | null;
  default_transfer_limit_irr: string | null;
  after_cutoff_transfer_limit_irr: string | null;
  cutoff_time: string | null;
  splitting_enabled: boolean;
  supports_description_field: boolean;
  config_hash: string;
  created_at: string;
}>;

/**
 * A bank and every configuration it has had.
 *
 * `current_version_id` is the profile's own pointer. The screen renders *that* as "in force"
 * rather than searching the list for `status === "active"` — the two must agree, and a screen that
 * derived it would hide the one disagreement an operator needs to see.
 */
export type BankProfileDetail = Readonly<{
  id: string;
  code: string;
  name: string;
  status: string;
  current_version_id: string | null;
  versions: readonly BankProfileVersion[];
}>;

export type BankAccount = Readonly<{
  id: string;
  display_name: string;
  account_role: string;
  status: string;
  /** Masked to the last four digits unless the caller holds `source_bank_account.manage`. */
  normalized_iban: string | null;
}>;

export async function listBankProfiles(signal?: AbortSignal): Promise<readonly BankProfileSummary[]> {
  const response = await transport.request<{ bank_profiles: readonly BankProfileSummary[] }>({
    method: "GET",
    path: "/bank-profiles",
    ...(signal ? { signal } : {}),
  });
  return response.data.bank_profiles;
}

export async function readBankProfile(
  profileId: string,
  signal?: AbortSignal,
): Promise<BankProfileDetail> {
  const response = await transport.request<BankProfileDetail>({
    method: "GET",
    path: `/bank-profiles/${encodeURIComponent(profileId)}`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * Create a bank and its first configuration, in one transaction.
 *
 * The limits are sent as numbers because the request model takes integers — the *response* and
 * read contract carry strings, and the asymmetry is the backend's, not this module's invention.
 * The form collects digits and this is the one place that converts, so there is a single line to
 * look at when a limit looks wrong.
 */
export async function createBankProfile(
  input: Readonly<{
    code: string;
    displayName: string;
    defaultTransferLimitIrr?: string;
    afterCutoffTransferLimitIrr?: string;
    splittingEnabled: boolean;
    supportsDescriptionField: boolean;
  }>,
): Promise<{ profile_id: string; version_id: string }> {
  const response = await transport.request<
    { profile_id: string; version_id: string },
    Record<string, unknown>
  >({
    method: "POST",
    path: "/bank-profiles",
    body: {
      code: input.code,
      display_name: input.displayName,
      default_transfer_limit_irr: digitsOrNull(input.defaultTransferLimitIrr),
      after_cutoff_transfer_limit_irr: digitsOrNull(input.afterCutoffTransferLimitIrr),
      splitting_enabled: input.splittingEnabled,
      supports_description_field: input.supportsDescriptionField,
    },
  });
  return response.data;
}

/**
 * Put a configuration into force.
 *
 * **No `If-Match` and no `Idempotency-Key`, and neither is an omission.** `BankProfileVersion`
 * carries no `record_version` — a version is superseded by inserting a new row, never edited — so
 * there is nothing for a precondition to be stale against, and `command_catalog.yaml` asks for
 * `lock_profile_and_active_version`, a server-side lock. The route accepts neither header;
 * sending one would be this screen inventing a control.
 */
export async function activateBankProfileVersion(versionId: string): Promise<void> {
  await transport.request({
    method: "POST",
    path: `/bank-profile-versions/${encodeURIComponent(versionId)}/activate`,
  });
}

export async function listBankAccounts(signal?: AbortSignal): Promise<readonly BankAccount[]> {
  const response = await transport.request<{ bank_accounts: readonly BankAccount[] }>({
    method: "GET",
    path: "/bank-accounts",
    ...(signal ? { signal } : {}),
  });
  return response.data.bank_accounts;
}

export async function createBankAccount(
  input: Readonly<{
    profileId: string;
    displayName: string;
    accountRole: string;
    normalizedIban?: string;
  }>,
): Promise<BankAccount> {
  const response = await transport.request<BankAccount, Record<string, unknown>>({
    method: "POST",
    path: "/bank-accounts",
    body: {
      profile_id: input.profileId,
      display_name: input.displayName,
      account_role: input.accountRole,
      normalized_iban: input.normalizedIban?.trim() ? input.normalizedIban.trim() : null,
    },
  });
  return response.data;
}

/**
 * A digit string as the integer the create request wants, or `null` for "this bank publishes none".
 *
 * **Empty is `null`, not zero.** The column is null-tolerant precisely because those mean
 * different things: null is "no published limit", zero would mean every transfer must be split
 * into nothing. A form that sent `0` for a blank field would encode the second while a person
 * meant the first.
 */
function digitsOrNull(value: string | undefined): number | null {
  const trimmed = (value ?? "").trim();
  return trimmed === "" ? null : Number(trimmed);
}
