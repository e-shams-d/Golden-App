/**
 * The trader's session, loaded at runtime.
 *
 * `traderAuthAdapter` has existed since slice 9 with a complete `loadSession`, and it was
 * **exported and imported nowhere** — the same gap the admin app had until slice 10D, left
 * on this side because no trader screen needed it yet. It needed it the moment somebody
 * tried to sign in: the home page showed a shell with no way to reach `/login`, so a
 * goldsmith arriving at the application had nowhere to go.
 *
 * Deliberately mirrors `apps/admin-web/src/session.ts` rather than sharing with it.
 * `UI-ISO-001` requires that neither bundle contain the other's endpoint paths, and a
 * shared module holding both would put the admin session route into this bundle.
 */

import type { SessionSnapshot } from "@gold/auth-client";

import { traderAuthAdapter } from "./auth";

export type TraderSession =
  | { readonly kind: "loading" }
  | { readonly kind: "anonymous" }
  | { readonly kind: "signed-in"; readonly subjectId: string };

export async function loadTraderSession(signal?: AbortSignal): Promise<TraderSession> {
  const snapshot: SessionSnapshot = await traderAuthAdapter.loadSession(signal);

  if (snapshot.state !== "authenticated" || !snapshot.identity) {
    return { kind: "anonymous" };
  }
  return { kind: "signed-in", subjectId: snapshot.identity.subjectId };
}
