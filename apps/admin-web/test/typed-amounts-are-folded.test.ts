import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * An amount a person typed is folded before it is sent.
 *
 * **The wire form is ASCII by decision, not by omission.**
 * `tests/backend/test_payment_amount_wire.py` records it: *"the Arabic-Indic digits
 * because the wire form is ASCII — `normalize_iban` folds digits for an IBAN a human
 * types, but an amount arrives from a program."* An IBAN is normalised server-side and
 * checked by its own check digits; an amount has no such check, so coercing one is a
 * different risk. The screen holds the other end of that bargain.
 *
 * `requests/new/page.tsx` already did — `normalizeDigits(value).trim()`, with a comment
 * saying a Persian keyboard produces `۱۲۳`. Three screens did not, and the failure was
 * worse than the 422 the finding described: `Number` of a Persian numeral is `NaN`, and
 * `JSON.stringify` writes `NaN` as `null`. A trader claiming a payment on an Iranian
 * phone sent a null amount.
 *
 * **Keyed on `Number(` applied to state, not on the word "amount".** A screen that
 * displays an amount needs nothing; one that parses typed text into a number is making
 * the conversion this is about. Formatting helpers are excluded by name because they
 * read a value the server sent.
 *
 * Covers: F-25.
 */

const APPS = ["admin-web", "trader-pwa"] as const;
const ROOT = join(import.meta.dirname, "..", "..", "..", "apps");

const code = (path: string): string =>
  readFileSync(path, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/^\s*\/\/.*$/gm, "");

/** `Number(x)` where `x` is a bare identifier — typed text on its way to a request. */
const NUMBER_OF_STATE = /Number\(\s*([A-Za-z_$][\w$]*)\s*\)/gu;

const pages = (app: string): string[] => {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name === ".next") continue;
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".tsx")) out.push(full);
    }
  };
  walk(join(ROOT, app, "app"));
  return out;
};

describe("an amount a person typed", () => {
  it("finds pages to check, so the assertion below is not vacuous", () => {
    for (const app of APPS) {
      expect(pages(app).length, `${app} has no pages`).toBeGreaterThan(5);
    }
  });

  it("is never parsed straight from component state", () => {
    const offenders: string[] = [];
    for (const app of APPS) {
      for (const path of pages(app)) {
        const source = code(path);
        for (const match of source.matchAll(NUMBER_OF_STATE)) {
          const name = match[1];
          // A value the server sent, read back for display or arithmetic, was never
          // typed. Only state a `useState` declares as text can carry a Persian digit.
          // Index arithmetic, with no escape sequence anywhere in it. Two earlier versions
          // of this check carried one — a template-literal backslash, then a newline escape
          // — and each was flattened before the file was written, leaving a pattern that
          // matched nothing while the gate reported success. There is nothing here to eat.
          const at = source.indexOf(`const [${name},`);
          const declared =
            at >= 0 && source.slice(at, at + 120).includes('useState("")');
          if (!declared) continue;
          offenders.push(`${path.slice(path.indexOf("apps/"))} → Number(${name})`);
        }
      }
    }
    expect(
      offenders,
      "these parse typed text into a number without folding first, and `Number` of a " +
        "Persian numeral is NaN, which JSON.stringify writes as null: " +
        offenders.join(", "),
    ).toEqual([]);
  });

  it("still has screens that do the folding, so the rule is being met rather than dodged", () => {
    // The guard on the assertion above: it would also pass if every amount input were
    // deleted. At least the four known call sites must still fold.
    const folding = APPS.flatMap((app) =>
      pages(app).filter((path) => code(path).includes("normalizeDigits(")),
    );
    expect(folding.length).toBeGreaterThanOrEqual(4);
  });
});
