import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * No browser converts money. `UI-REQ-003`'s other half, over the source rather than a value.
 *
 * `request-view.test.ts` proves the display path passes the server's digits through. This
 * proves nobody added a second path: a helper somewhere else, a live "= X ریال" preview under
 * an amount field, a total in a summary panel. Each of those is the conversion
 * `15_Agent_Implementation_Plan.md:802` puts on the server, wearing a label that says it is
 * only a hint — and the first time the two disagreed, a goldsmith would authorise an amount
 * the platform does not hold.
 *
 * Both apps are scanned from here, and deliberately: the admin bundle renders the same
 * amounts, and a conversion on the reviewer's screen would make the accountant and the trader
 * read different numbers for one request. `UI-ISO-001` forbids the two bundles naming each
 * other's endpoints; a test reading the other's files crosses no such line.
 *
 * The pattern is the factor itself. Ten is the whole of the IRR/TOMAN relation, so `* 10`,
 * `/ 10`, `10 *` and `1e1` are what a conversion has to be spelled as.
 *
 * **There is one legitimate ten, and I claimed there were none.** This file first said no
 * interface source multiplies by ten, which was asserted rather than checked:
 * `src/evidence.ts` computes a byte ceiling as `10 * 1024 * 1024`. So the exception is named
 * and narrow — a line whose ten sits beside `1024` is a size, not a currency — and the
 * pattern test below asserts that the exception does not swallow a real conversion. A blanket
 * refusal with one written-down exception is worth more than a looser rule that never had to
 * admit anything.
 *
 * Covers: UI-REQ-003.
 */

const APPS_ROOT = join(import.meta.dirname, "..", "..");
const SCANNED = [
  join(APPS_ROOT, "trader-pwa", "app"),
  join(APPS_ROOT, "trader-pwa", "src"),
  join(APPS_ROOT, "trader-pwa", "components"),
  join(APPS_ROOT, "admin-web", "app"),
  join(APPS_ROOT, "admin-web", "src"),
  join(APPS_ROOT, "admin-web", "components"),
];

/** `*10`, `* 10`, `/10`, `10 *`, `10*`, and the exponent spelling. Not `100`, not `10.5`. */
const CONVERSION = /(?:[*/]\s*10(?![\d.])|(?<![\d.])10\s*\*)|\b1e1\b/;

/**
 * The named exception, as narrow as the idiom it excuses: `10 * 1024` and nothing looser.
 *
 * A whole-line "contains 1024" rule would have let `const rials = toman * 10;` through on any
 * line that also mentioned a buffer size. That is how a narrow exception becomes a wide one
 * without anybody deciding to widen it, so the ten and the 1024 have to be the same
 * expression.
 */
const BYTE_SIZE = /10\s*\*\s*1024/;

function isMoneyConversion(code: string): boolean {
  return CONVERSION.test(code) && !BYTE_SIZE.test(code);
}

function sources(directory: string): readonly string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      found.push(...sources(path));
    } else if (/\.tsx?$/.test(entry)) {
      found.push(path);
    }
  }
  return found;
}

describe("money conversion never happens in a browser", () => {
  it("finds files to scan at all", () => {
    // Guard the guard: a wrong path would make every assertion below vacuous, and the
    // failure would look exactly like success.
    const all = SCANNED.flatMap(sources);

    expect(all.length).toBeGreaterThan(15);
    expect(all.some((path) => path.endsWith(join("src", "payment-requests.ts")))).toBe(true);
    expect(all.some((path) => path.endsWith(join("src", "request-view.ts")))).toBe(true);
  });

  it("has no ten-times factor in any interface source", () => {
    const offenders: string[] = [];
    for (const path of SCANNED.flatMap(sources)) {
      const lines = readFileSync(path, "utf8").split("\n");
      lines.forEach((line, index) => {
        // Comments are allowed to discuss the factor; this file and several docstrings do.
        const code = line.replace(/\/\/.*$/, "").replace(/\/\*.*?\*\//g, "");
        if (isMoneyConversion(code)) offenders.push(`${path}:${index + 1}: ${line.trim()}`);
      });
    }

    expect(
      offenders,
      "these lines multiply or divide by ten in a browser, which is the IRR/TOMAN " +
        "conversion the server owns:\n" +
        offenders.join("\n"),
    ).toEqual([]);
  });

  it("recognises a conversion when there is one", () => {
    // The negative control, permanent rather than performed once: if the pattern stopped
    // matching, the test above would pass over a real conversion.
    for (const written of [
      "const rials = toman * 10;",
      "const rials = toman*10;",
      "const toman = rials / 10;",
      "const rials = 10 * toman;",
      "const rials = toman * 1e1;",
    ]) {
      expect(isMoneyConversion(written), written).toBe(true);
    }

    // And does not fire on arithmetic that is not the factor.
    for (const innocent of [
      "const width = size * 100;",
      "const half = total / 2;",
      "rows.slice(0, 10);",
      "const ratio = value * 10.5;",
      // The named exception, which is the one real ten in these bundles.
      "maxBytes: 10 * 1024 * 1024,",
    ]) {
      expect(isMoneyConversion(innocent), innocent).toBe(false);
    }
  });

  it("still catches a conversion that shares a line with a byte size", () => {
    // The exception is the expression `10 * 1024`, not the presence of 1024 somewhere on the
    // line. A looser rule would have excused this, which is the hole worth having a test for
    // rather than a comment about.
    expect(isMoneyConversion("const rials = toman * 10; const cap = 1024;")).toBe(true);
    expect(isMoneyConversion("const rials = toman / 10; // buffer is 1024")).toBe(true);
  });
});
