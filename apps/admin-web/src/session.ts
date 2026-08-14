/**
 * The session, loaded at runtime — the thing this app has never done.
 *
 * `adminAuthAdapter` has existed since slice 9 with a complete `loadSession`, and it was
 * **exported and imported nowhere**. So `GET /auth/me` was never called by either app, the
 * shell rendered a literal "role unknown", and an authenticated administrator and an
 * anonymous visitor produced identical bytes. Two obligations — a landing surface that
 * differs by session, and navigation that reflects permissions — were owed to a mechanism
 * that had no caller, which is the third time in this milestone that has been the finding.
 *
 * **Loaded on the client, not on the server.** The session is a `__Host-` prefixed cookie
 * and the app is exported for a static shell; a server component would need the cookie
 * forwarded through the Next server, which is a second path to the same answer and one more
 * place for the audience to be resolved wrongly. The client already holds the cookie and
 * the browser already attaches it.
 *
 * **A failure to load is `unauthenticated`, never an error state.** Somebody who is not
 * signed in is the ordinary case for this call, not a fault, and the shell renders the
 * signed-out surface for both. The distinction that matters — being signed out versus the
 * API being unreachable — is one this screen cannot make and would be guessing at.
 */

import type { SessionSnapshot } from "@gold/auth-client";

import { adminAuthAdapter } from "./auth";

export type AdminSession =
  | { readonly kind: "loading" }
  | { readonly kind: "anonymous" }
  | {
      readonly kind: "signed-in";
      readonly subjectId: string;
      readonly permissions: readonly string[];
      readonly expiresAt: string;
    };

export async function loadAdminSession(signal?: AbortSignal): Promise<AdminSession> {
  const snapshot: SessionSnapshot = await adminAuthAdapter.loadSession(signal);

  if (snapshot.state !== "authenticated" || !snapshot.identity) {
    return { kind: "anonymous" };
  }

  return {
    kind: "signed-in",
    subjectId: snapshot.identity.subjectId,
    // Consumed for navigation only. The backend resolves grants on every request
    // (`app/api/v1/auth.py`), so this copy is a hint about what to show and never a
    // decision about what is allowed.
    permissions: snapshot.identity.permissions ?? [],
    expiresAt: snapshot.expiresAt ?? "",
  };
}
