export type SessionLifecycleState =
  | "unknown"
  | "unauthenticated"
  | "authenticated"
  | "expired"
  | "revoked"
  | "reauthentication_required";

export type IdentityDomain = "trader" | "internal";

export type SessionIdentity = Readonly<{
  subjectId: string;
  displayName: string;
  domain: IdentityDomain;
  permissions: readonly string[];
}>;

export type SessionSnapshot = Readonly<{
  state: SessionLifecycleState;
  identity?: SessionIdentity;
  expiresAt?: string;
}>;

export type RecentAuthContext = Readonly<{
  reference: string;
  actionClass: string;
  expiresAt: string;
  /**
   * What this context authorises. Carried, not optional.
   *
   * `FINANCIAL_INTEGRITY_BASELINE.md` §3 binds a recent-auth context to a resource, and
   * `app/security/step_up.py` names the case in its own docstring: "otherwise a step-up for batch
   * version 7 authorises version 8, which is the case the whole approval model exists to
   * prevent". The server refuses a mismatch with `WRONG_RESOURCE`; carrying the binding here is
   * what stops the client presenting one it already knows will be refused.
   */
  resourceType: string;
  resourceId: string;
}>;

export type ReauthenticateInput = Readonly<{
  actionClass: string;
  challengeResponse: string;
  /**
   * The resource binding the approved baseline requires.
   *
   * Added by M7's screens slice 2, which is the caller `apps/admin-web/src/auth.ts` was waiting
   * for: its `reauthenticate` threw
   * `step_up_requires_a_resource_binding_supplied_by_the_calling_screen`, because sending a
   * placeholder would have bound a context to nothing. This is the screen supplying it.
   */
  resourceType: string;
  resourceId: string;
  signal?: AbortSignal;
}>;

export type AuthAdapter = Readonly<{
  loadSession: (signal?: AbortSignal) => Promise<SessionSnapshot>;
  logout: (signal?: AbortSignal) => Promise<void>;
  reauthenticate: (
    input: ReauthenticateInput,
  ) => Promise<RecentAuthContext>;
}>;

export type AuthClient = Readonly<{
  getSnapshot: () => SessionSnapshot;
  subscribe: (listener: (snapshot: SessionSnapshot) => void) => () => void;
  refresh: (signal?: AbortSignal) => Promise<SessionSnapshot>;
  logout: (signal?: AbortSignal) => Promise<void>;
  markExpired: () => void;
  markRevoked: () => void;
  reauthenticate: (
    input: ReauthenticateInput,
  ) => Promise<RecentAuthContext>;
  getRecentAuth: (actionClass: string, resourceId?: string) => RecentAuthContext | undefined;
  clearRecentAuth: () => void;
}>;
