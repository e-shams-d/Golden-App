import { describe, expect, it, vi } from "vitest";

import { createAuthClient, type AuthAdapter } from "../src";

/**
 * Two version ids, because a recent-auth context is bound to one and the whole point is that it
 * does not authorise the other. M7's screens slice 2 added the binding; before it, matching on
 * the action class alone was correct.
 */
const VERSION = "11111111-1111-4111-8111-111111111111";
const OTHER_VERSION = "22222222-2222-4222-8222-222222222222";

describe("ADR-neutral auth client", () => {
  it("keeps recent authentication in memory and clears it on expiry", async () => {
    const adapter: AuthAdapter = {
      loadSession: vi.fn(async () => ({ state: "authenticated" as const })),
      logout: vi.fn(async () => undefined),
      reauthenticate: vi.fn(async ({ actionClass, resourceType, resourceId }) => ({
        reference: "recent-auth-reference",
        actionClass,
        expiresAt: new Date(Date.now() + 60_000).toISOString(),
        resourceType,
        resourceId,
      })),
    };
    const client = createAuthClient(adapter);

    await client.reauthenticate({
      actionClass: "payment_batch_version.approve",
      challengeResponse: "opaque-response",
      resourceType: "payment_batch_version",
      resourceId: VERSION,
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
      reauthenticate: vi.fn(async ({ actionClass, resourceType, resourceId }) => ({
        reference: "invalid-recent-auth-reference",
        actionClass,
        expiresAt: "not-a-timestamp",
        resourceType,
        resourceId,
      })),
    };
    const client = createAuthClient(adapter);

    await client.reauthenticate({
      actionClass: "payment_batch_version.approve",
      challengeResponse: "opaque-response",
      resourceType: "payment_batch_version",
      resourceId: VERSION,
    });

    expect(client.getRecentAuth("payment_batch_version.approve")).toBeUndefined();
  });

  it("does not hand a context for one version back for another", async () => {
    // The failure `app/security/step_up.py` names in its own docstring: "otherwise a step-up for
    // batch version 7 authorises version 8, which is the case the whole approval model exists to
    // prevent". Matching on the action class alone was correct until a context carried a binding;
    // it became wrong the moment M7's screens slice 2 gave it one.
    //
    // The server refuses the mismatch with `WRONG_RESOURCE`, so the cost of getting this wrong is
    // not a hole — it is a manager spending a single-use assurance to learn they needed another.
    const adapter: AuthAdapter = {
      loadSession: vi.fn(async () => ({ state: "authenticated" as const })),
      logout: vi.fn(async () => undefined),
      reauthenticate: vi.fn(async ({ actionClass, resourceType, resourceId }) => ({
        reference: "a-valid-reference",
        actionClass,
        expiresAt: new Date(Date.now() + 300_000).toISOString(),
        resourceType,
        resourceId,
      })),
    };
    const client = createAuthClient(adapter);

    await client.reauthenticate({
      actionClass: "payment_batch_version.approve",
      challengeResponse: "opaque-response",
      resourceType: "payment_batch_version",
      resourceId: VERSION,
    });

    expect(client.getRecentAuth("payment_batch_version.approve", VERSION)).toBeDefined();
    expect(client.getRecentAuth("payment_batch_version.approve", OTHER_VERSION)).toBeUndefined();
    // Asked without a resource, the held context still comes back: callers with nothing to bind
    // keep working, and there are none today.
    expect(client.getRecentAuth("payment_batch_version.approve")).toBeDefined();
  });

  it("does not hand an approve context back for a reject", async () => {
    // Two purposes rather than one, so re-authenticating to refuse a batch cannot be spent
    // authorising it. §3 of the baseline lists action alongside resource, and the two failures
    // differ in kind: the wrong resource pays the wrong people, the wrong action pays them when
    // somebody meant to stop it.
    const adapter: AuthAdapter = {
      loadSession: vi.fn(async () => ({ state: "authenticated" as const })),
      logout: vi.fn(async () => undefined),
      reauthenticate: vi.fn(async ({ actionClass, resourceType, resourceId }) => ({
        reference: "a-valid-reference",
        actionClass,
        expiresAt: new Date(Date.now() + 300_000).toISOString(),
        resourceType,
        resourceId,
      })),
    };
    const client = createAuthClient(adapter);

    await client.reauthenticate({
      actionClass: "payment_batch_version.approve",
      challengeResponse: "opaque-response",
      resourceType: "payment_batch_version",
      resourceId: VERSION,
    });

    expect(client.getRecentAuth("payment_batch_version.reject", VERSION)).toBeUndefined();
  });
});
