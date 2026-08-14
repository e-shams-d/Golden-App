import { readFileSync } from "node:fs";
import { join } from "node:path";

import { APPLICATION_STATES, OWED_STATES, STATE_FOR_CODE } from "@gold/api-client";
import { KIND_FOR_APPLICATION_STATE, STATE_KINDS, kindForApplicationState } from "@gold/ui";
import { describe, expect, it } from "vitest";

/**
 * The seam between "what happened" and "what it looks like".
 *
 * `@gold/api-client` decides which of document 21's eighteen states a response means;
 * `@gold/ui` decides which of eight kinds renders it. **Neither imports the other**, and
 * that is deliberate: `packages/ui` is presentation, and a component package that depended
 * on the API client could not be rendered without HTTP.
 *
 * The cost of that isolation is two tables keyed on the same eighteen strings with nothing
 * holding them together — so this file is what holds them together. It lives here because
 * `admin-web` is a place that already depends on both; a compile-time link would have
 * required exactly the dependency the split avoids.
 *
 * A drift here is not cosmetic. A state with no kind renders through
 * `kindForApplicationState`'s `error` fallback, which means a person meeting a *stale
 * version* would be told something went wrong instead of being told to reload — and
 * nothing would report it, because the fallback is a successful render.
 *
 * Covers: UI-STATE-001.
 */

const REPOSITORY_ROOT = join(import.meta.dirname, "..", "..", "..");
const MESSAGES = join(REPOSITORY_ROOT, "packages", "localization", "src", "messages.ts");

describe("the two state tables", () => {
  it("has states to compare, so the checks below are not vacuous", () => {
    expect(APPLICATION_STATES.length).toBe(18);
    expect(STATE_KINDS.length).toBeGreaterThanOrEqual(8);
  });

  it("gives every application state a kind", () => {
    const missing = APPLICATION_STATES.filter((state) => !(state in KIND_FOR_APPLICATION_STATE));

    expect(
      missing,
      "these states would render through the `error` fallback, which is a successful " +
        "render of the wrong thing and reports nothing",
    ).toEqual([]);
  });

  it("names no kind the component does not have", () => {
    const kinds = new Set<string>(STATE_KINDS);
    const invented = Object.entries(KIND_FOR_APPLICATION_STATE)
      .filter(([, kind]) => !kinds.has(kind))
      .map(([state]) => state);

    expect(invented).toEqual([]);
  });

  it("maps no state the API client does not know", () => {
    const known = new Set<string>(APPLICATION_STATES);
    const orphans = Object.keys(KIND_FOR_APPLICATION_STATE).filter((state) => !known.has(state));

    expect(orphans, "a kind for a state nothing can produce is a row nobody will ever hit").toEqual(
      [],
    );
  });

  it("keeps stale version, workflow rejection and idempotency conflict visually distinct", () => {
    // The three the server distinguishes and a screen must not collapse: reloading fixes
    // the first, re-presents the second, and is the wrong advice entirely for the third.
    expect(kindForApplicationState("stale-version")).toBe("conflict");
    expect(kindForApplicationState("workflow-rejection")).toBe("error");
    expect(kindForApplicationState("idempotency-conflict")).toBe("idempotency");
  });

  it("does not render an expired session as a permission problem", () => {
    // `forbidden` sends somebody to an administrator. An expired session needs the login
    // form, and the two are one keystroke apart in a table like this.
    expect(kindForApplicationState("session-expired")).not.toBe("forbidden");
    expect(kindForApplicationState("permission-denied")).toBe("forbidden");
  });
});

describe("the wording every kind renders", () => {
  const messages = readFileSync(MESSAGES, "utf8");

  it("has a Persian title and description for every kind", () => {
    // A kind with no message renders `undefined` through `t()`, which is a blank panel —
    // and the three added in this slice are exactly the kinds nothing had wording for.
    for (const kind of STATE_KINDS) {
      expect(messages, `state.${kind}.title is missing`).toContain(`"state.${kind}.title":`);
      expect(messages, `state.${kind}.description is missing`).toContain(
        `"state.${kind}.description":`,
      );
    }
  });

  it("does not tell somebody an uncertain outcome failed", () => {
    // The wording is the control for this state, not the styling. A person told an
    // operation failed retries it, and `timeout-uncertain` is precisely the case where a
    // retry could apply the same change twice.
    const timeout = /"state\.timeout\.(title|description)": "([^"]*)"/g;
    const rendered = [...messages.matchAll(timeout)].map((match) => match[2]!);

    expect(rendered.length, "the timeout wording was not found to check").toBe(2);
    for (const text of rendered) {
      expect(text, `the timeout wording claims failure: ${text}`).not.toContain("انجام نشد");
      expect(text).not.toContain("ناموفق");
    }
    // And the positive half: it has to say the outcome is unknown, or "does not claim
    // failure" is satisfied by wording that says nothing at all.
    expect(rendered.join(" ")).toContain("مشخص نیست");
  });
});

describe("what the owed states admit", () => {
  it("still has a kind for each, so an owed state is not an unrenderable one", () => {
    // Being owed means no error code reaches it yet. It does not mean a screen that sets
    // it directly — a loading spinner, an empty list — has nothing to draw.
    for (const state of Object.keys(OWED_STATES)) {
      expect(KIND_FOR_APPLICATION_STATE[state], `${state} is owed and unrenderable`).toBeDefined();
    }
  });

  it("owes only what no code produces", () => {
    const reachable = new Set(Object.values(STATE_FOR_CODE));
    for (const state of Object.keys(OWED_STATES)) {
      expect(reachable.has(state as never), `${state} is both owed and reachable`).toBe(false);
    }
  });
});
