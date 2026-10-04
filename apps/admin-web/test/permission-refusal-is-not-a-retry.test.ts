import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * A command error mapped by hand must distinguish a refusal from a fault.
 *
 * F-1: an accountant on `/traders` sees approve and reject, holds no `trader.approve`,
 * and the server refuses correctly with a 403. The screen said *"could not record the
 * decision. Refresh the list and try again"* — a **permission refusal** presented as a
 * **transient fault**, inviting a retry that can never succeed.
 *
 * The sweep that followed is why this is a gate and not a one-line fix: ten more call
 * sites across eight files had the identical shape and no 403 branch. Five other admin
 * screens do map 403, which makes these an omission rather than a convention.
 *
 * **Per call site, not per file, and that distinction is the whole gate.** The first
 * version of this test asked whether a file mentioned 403 anywhere. `traders/page.tsx`
 * does — its list-load handler maps 403 to a forbidden state — so that version stayed
 * green on the exact defect it was written for. The sabotage control caught it; nothing
 * else would have.
 *
 * **Why the rule keys on 412.** A screen routing errors through `stateForError` has the
 * mapping already and needs nothing here. A screen reaching past it to test a status
 * itself has taken on the job, and the one code it is certain to think of is the one it
 * was written for.
 *
 * A fallback that renders the server's own message is not caught and should not be:
 * `requests/[requestId]/publication` falls back to `body ?? t(...)`, so a 403 there
 * already shows what the server said, and a generic string would lose information.
 *
 * Covers: F-1.
 */

const APPS = ["admin-web", "trader-pwa"] as const;
const ROOT = join(import.meta.dirname, "..", "..", "..", "apps");

/** Comments removed, then whitespace collapsed: the wrapped and one-line forms are one shape. */
const flattened = (path: string): string =>
  readFileSync(path, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\s+/g, " ");

/** `status === 412 ? t(…) : t(…)` — straight from a stale precondition to one message. */
const TWO_WAY = /status === 412 \? t\([^)]*\) : t\(/gu;

/** A fallback that shows what the server said is more informative, not less. */
const SERVER_MESSAGE = /body \?\? t\(/u;

const pages = (app: string): string[] => {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name === ".next") continue;
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".tsx") || entry.name.endsWith(".ts")) out.push(full);
    }
  };
  walk(join(ROOT, app, "app"));
  return out;
};

describe("a permission refusal is not something to retry", () => {
  it("finds pages to check, so the assertion below is not vacuous", () => {
    for (const app of APPS) {
      expect(pages(app).length, `${app} has no pages`).toBeGreaterThan(5);
    }
  });

  it("recognises how many screens map a status by hand, so the sweep stays honest", () => {
    // If this ever reads zero, the pattern has stopped matching the code rather than the
    // code having stopped doing it — and the assertion below would pass by finding none.
    const handlers = APPS.flatMap((app) =>
      pages(app).filter((path) => flattened(path).includes("status === 412")),
    );
    expect(handlers.length).toBeGreaterThanOrEqual(8);
  });

  it("never sends a 403 to the generic branch", () => {
    const offenders: string[] = [];
    for (const app of APPS) {
      for (const path of pages(app)) {
        const source = flattened(path);
        if (SERVER_MESSAGE.test(source)) continue;
        const hits = source.match(TWO_WAY) ?? [];
        // One entry per call site, so a file with two unfixed handlers is named twice.
        for (let seen = 0; seen < hits.length; seen += 1) {
          offenders.push(path.slice(path.indexOf("apps/")));
        }
      }
    }
    expect(
      offenders,
      "these call sites go straight from a stale precondition to a generic message, so a " +
        "permission refusal reaches the person as a transient error they are invited to " +
        `retry: ${offenders.join(", ")}`,
    ).toEqual([]);
  });
});
