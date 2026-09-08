/**
 * Changing your own password.
 * `05_API_Specification.md` §8, and `12_Security_RBAC_Audit.md`'s own-credential rule.
 *
 * M11 Screens, slice 10. The route has existed since M3 and nothing has ever called it — slice 8's
 * Definition of Done gate is what made that visible, recording it as "no screen changes a password
 * yet". A person who signs in for the first time has no way to replace the password they were
 * given.
 *
 * **No permission and no `If-Match`, and the contract agrees on both.** The caller comes from the
 * session rather than from the body, so there is no id to authorise against; and the presence
 * check is the *current password*, which is a better precondition than a version — it proves the
 * person at the keyboard is the one whose credential this is.
 *
 * **Per-app and duplicated, per `UI-ISO-001`.** Both audiences call this one path under one guard.
 * That makes a shared module look obviously right, and it is the case the rule exists for: a
 * shared module is one import away from carrying the other side's paths.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/**
 * Replace the caller's own password.
 *
 * Returns `{ changed: true }`. The screen re-states that in words rather than showing the flag,
 * because "changed: true" is a fact about a response and a person needs a fact about their
 * account.
 *
 * **The server refuses a wrong current password with a 403**, and the screen says so plainly.
 * Telling somebody their new password was rejected when what failed was the old one is the kind
 * of error message that costs a support call.
 */
export async function changeOwnPassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ changed: boolean }> {
  const response = await transport.request<
    { changed: boolean },
    { current_password: string; new_password: string }
  >({
    method: "POST",
    path: "/auth/change-password",
    body: { current_password: currentPassword, new_password: newPassword },
  });
  return response.data;
}
