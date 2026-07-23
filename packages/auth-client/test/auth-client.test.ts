import { describe, expect, it, vi } from "vitest";

import { createAuthClient, type AuthAdapter } from "../src";

describe("ADR-neutral auth client", () => {
  it("keeps recent authentication in memory and clears it on expiry", async () => {
    const adapter: AuthAdapter = {
      loadSession: vi.fn(async () => ({ state: "authenticated" as const })),
      logout: vi.fn(async () => undefined),
      reauthenticate: vi.fn(async ({ actionClass }) => ({
        reference: "recent-auth-reference",
        actionClass,
        expiresAt: new Date(Date.now() + 60_000).toISOString(),
      })),
    };
    const client = createAuthClient(adapter);

    await client.reauthenticate({
      actionClass: "payment_batch_version.approve",
      challengeResponse: "opaque-response",
    });
    expect(client.getRecentAuth("payment_batch_version.approve")?.reference).toBe(
      "recent-auth-reference",
    );

    client.markExpired();
    expect(client.getRecentAuth("payment_batch_version.approve")).toBeUndefined();
    expect(client.getSnapshot().state).toBe("expired");
  });

  it("fails closed when a recent-auth expiry is malformed", async () => {
    const adapter: AuthAdapter = {
      loadSession: vi.fn(async () => ({ state: "authenticated" as const })),
      logout: vi.fn(async () => undefined),
      reauthenticate: vi.fn(async ({ actionClass }) => ({
        reference: "invalid-recent-auth-reference",
        actionClass,
        expiresAt: "not-a-timestamp",
      })),
    };
    const client = createAuthClient(adapter);

    await client.reauthenticate({
      actionClass: "payment_batch_version.approve",
      challengeResponse: "opaque-response",
    });

    expect(client.getRecentAuth("payment_batch_version.approve")).toBeUndefined();
  });
});
