import type {
  AuthAdapter,
  AuthClient,
  ReauthenticateInput,
  RecentAuthContext,
  SessionSnapshot,
} from "./types";

const INITIAL_SNAPSHOT: SessionSnapshot = { state: "unknown" };

/**
 * ADR-neutral session coordinator. It holds only current UI state and a
 * short-lived recent-auth reference in memory. It never persists credentials,
 * decides permissions, or replays a financial command.
 */
export function createAuthClient(adapter: AuthAdapter): AuthClient {
  let snapshot = INITIAL_SNAPSHOT;
  let recentAuth: RecentAuthContext | undefined;
  const listeners = new Set<(value: SessionSnapshot) => void>();

  const publish = (next: SessionSnapshot): SessionSnapshot => {
    snapshot = next;
    for (const listener of listeners) listener(snapshot);
    return snapshot;
  };

  const clearRecentAuth = (): void => {
    recentAuth = undefined;
  };

  return {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    async refresh(signal) {
      const next = await adapter.loadSession(signal);
      if (next.state !== "authenticated") clearRecentAuth();
      return publish(next);
    },
    async logout(signal) {
      await adapter.logout(signal);
      clearRecentAuth();
      publish({ state: "unauthenticated" });
    },
    markExpired() {
      clearRecentAuth();
      publish({ state: "expired" });
    },
    markRevoked() {
      clearRecentAuth();
      publish({ state: "revoked" });
    },
    async reauthenticate(input: ReauthenticateInput) {
      const context = await adapter.reauthenticate(input);
      if (context.actionClass !== input.actionClass) {
        throw new Error("Recent-auth context does not match the requested action class.");
      }
      recentAuth = context;
      return context;
    },
    /**
     * The held context, if it authorises **this** action on **this** resource.
     *
     * `resourceId` became part of the question in M7's screens slice 2, and matching on the
     * action class alone was wrong the moment a context carried a binding: a step-up obtained to
     * approve version 7 would have been handed back for version 8, which is precisely what
     * `app/security/step_up.py` exists to refuse. The server would have said `WRONG_RESOURCE` and
     * the caller would have spent a single-use assurance learning it.
     *
     * The resource is optional in the signature so callers with nothing to bind — none today —
     * keep working; when it is given, it must match.
     */
    getRecentAuth(actionClass, resourceId) {
      if (!recentAuth) return undefined;
      const expiresAt = Date.parse(recentAuth.expiresAt);
      if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
        clearRecentAuth();
        return undefined;
      }
      if (recentAuth.actionClass !== actionClass) return undefined;
      if (resourceId !== undefined && recentAuth.resourceId !== resourceId) return undefined;
      return recentAuth;
    },
    clearRecentAuth,
  };
}
