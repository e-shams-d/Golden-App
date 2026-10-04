import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * A screen that shows what the server said shows it in Persian.
 *
 * F-2 was recorded as one English string on `/admin-users`. It is the error envelope:
 * every constant message the server sends is English, and three screens rendered
 * `body.error.message` verbatim into a Persian interface.
 *
 * **This also corrects a reason I gave earlier.** The F-1 change deliberately left
 * `requests/[requestId]/publication` alone because its fallback "shows what the server
 * said, which is more informative than a generic string". The server says it in English,
 * so that fallback was more *specific* and no more *readable* — the exemption was right
 * about the information and wrong about the person.
 *
 * `errorMessage` keeps the split: a constant the server always sends is translated, a
 * message composed for one case passes through because it carries the only part a reader
 * can act on.
 *
 * No escape sequence is built into any pattern here. A check of this shape was silently
 * disarmed twice in this codebase by a lost backslash, and the only durable answer was to
 * have nothing to escape.
 */

const ROOT = join(import.meta.dirname, "..", "..", "..", "apps");

const code = (path: string): string =>
  readFileSync(path, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/^\s*\/\/.*$/gm, "");

const sources = (app: string): string[] => {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name === ".next") continue;
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".tsx") || entry.name.endsWith(".ts")) out.push(full);
    }
  };
  for (const part of ["app", "components", "src"]) {
    try {
      walk(join(ROOT, app, part));
    } catch {
      // Not every app has every directory.
    }
  }
  return out;
};

describe("what a refusal shows a person", () => {
  it("finds sources to check, so the assertion below is not vacuous", () => {
    for (const app of ["admin-web", "trader-pwa"]) {
      expect(sources(app).length, `${app} has no sources`).toBeGreaterThan(5);
    }
  });

  it("never renders the server's message without translating the constant ones", () => {
    const offenders: string[] = [];
    for (const app of ["admin-web", "trader-pwa"]) {
      for (const path of sources(app)) {
        const text = code(path);
        // The envelope's root, not one spelling of reading it. The first version of
        // this line looked for `error?.message`, and a sabotage that renamed the local
        // to `failure?.message` escaped the gate entirely — which the control caught by
        // producing no failure where one was required.
        if (!text.includes("body?.error")) continue;
        if (text.includes("errorMessage(")) continue;
        offenders.push(path.slice(path.indexOf("apps/")));
      }
    }
    expect(
      offenders,
      "these read the server's message and show it as it arrived, which for every " +
        "constant the server sends means English on a Persian screen: " +
        offenders.join(", "),
    ).toEqual([]);
  });

  it("still has screens that read it, so the rule is met rather than dodged", () => {
    // Without this, deleting every error display would satisfy the assertion above.
    const readers = ["admin-web", "trader-pwa"].flatMap((app) =>
      sources(app).filter((path) => code(path).includes("errorMessage(")),
    );
    expect(readers.length).toBeGreaterThanOrEqual(3);
  });
});
