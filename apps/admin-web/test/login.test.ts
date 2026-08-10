import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { GENERIC_LOGIN_FAILURE, readCsrfToken } from "../src/auth";

/**
 * Audience isolation and credential handling, checked in the source this app
 * actually bundles.
 *
 * `UI-ISO-001` wants the built output checked, and this is the cheaper half of
 * that: a path that never appears in the module graph cannot appear in the
 * bundle. The Playwright suite covers the browser half.
 *
 * Covers: UI-ISO-001, UI-STORE-001, UI-LOGIN-002.
 */

const APP_ROOT = join(import.meta.dirname, "..");

/**
 * Writes to browser storage, as regex **literals**.
 *
 * Deliberately not built with `new RegExp` over a template string. The first
 * version did, and inside a template literal `\b` is the escape for a backspace
 * character rather than a word boundary — so every pattern began with U+0008,
 * matched nothing, and the test passed over any source at all.
 */
const STORAGE_USAGE: readonly RegExp[] = [
  /\blocalStorage\s*[.[]/,
  /\bsessionStorage\s*[.[]/,
  /\bindexedDB\s*[.[]/,
] as const;

function source(...parts: string[]): string {
  return readFileSync(join(APP_ROOT, ...parts), "utf8");
}

describe("internal authentication wiring", () => {
  it("never names the trader audience's login route", () => {
    // UI-ISO-001. The route is the audience (DOC-CONFLICT-023), so naming the
    // other one is the only way this bundle could ask to be evaluated as a
    // trader.
    for (const file of [["src", "auth.ts"], ["app", "login", "page.tsx"]]) {
      expect(source(...file)).not.toContain("/auth/trader/login");
      expect(source(...file)).not.toContain("gp_trader_session");
      expect(source(...file)).not.toContain("gp_trader_csrf");
    }
  });

  it("names its own login route, so the check above is not vacuous", () => {
    expect(source("src", "auth.ts")).toContain("/auth/admin/login");
  });

  it("writes no credential to browser storage", () => {
    // UI-STORE-001. ADR-001 forbids a long-lived credential in localStorage, and
    // the session is an HttpOnly cookie this code cannot read even if it wanted
    // to. Asserted structurally because the positive version — inspecting storage
    // after a login — passes trivially while the code contains the write.
    const text = source("src", "auth.ts") + source("app", "login", "page.tsx");

    // Matched as *usage* rather than as the bare word: the version before this
    // one failed on a comment explaining that we do not use localStorage, and a
    // check a prose mention can trip is one somebody eventually satisfies by
    // deleting the explanation.
    for (const pattern of STORAGE_USAGE) {
      expect(text).not.toMatch(pattern);
    }
  });

  it("the storage patterns actually match a violation", () => {
    // Guard the guard, and it has already earned its place. An earlier version
    // built these patterns with `new RegExp` over a template literal, where `\b`
    // is a backspace rather than a word boundary — so nothing matched, the test
    // above passed, and it would have gone on passing over code that did write a
    // credential to storage.
    const violations = [
      'localStorage.setItem("session", token)',
      "window.sessionStorage.clear()",
      'indexedDB.open("creds")',
      'globalThis.localStorage["k"] = v',
    ];

    for (const violation of violations) {
      expect(STORAGE_USAGE.some((pattern) => pattern.test(violation))).toBe(true);
    }
  });

  it("exposes exactly one failure reason", () => {
    // UI-LOGIN-002. The backend answers one `UNAUTHENTICATED` for an unknown
    // number, a wrong password, a suspended account and a locked one; rendering
    // more would undo that on the client, and the client knows no more anyway.
    expect(GENERIC_LOGIN_FAILURE).toBe("invalid_credentials");
  });

  it("reads the CSRF token from its own cookie and no other", () => {
    const jar =
      "other=1; __Host-gp_trader_csrf=trader-token; __Host-gp_admin_csrf=admin-token; x=2";

    expect(readCsrfToken(jar)).toBe("admin-token");
    expect(readCsrfToken("__Host-gp_trader_csrf=trader-token")).toBeUndefined();
    expect(readCsrfToken("")).toBeUndefined();
  });

  it("does not mistake a cookie whose name merely ends the same way", () => {
    // `x__Host-gp_admin_csrf` is a different cookie. Splitting on `=` after
    // trimming compares the whole name, which a `includes()` check would not.
    expect(readCsrfToken("x__Host-gp_admin_csrf=wrong")).toBeUndefined();
  });
});
