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
}>;

export type ReauthenticateInput = Readonly<{
  actionClass: string;
  challengeResponse: string;
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
  getRecentAuth: (actionClass: string) => RecentAuthContext | undefined;
  clearRecentAuth: () => void;
}>;
