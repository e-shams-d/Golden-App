import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The `If-Match` a screen sends comes from the server's `ETag`, never from arithmetic.
 *
 * Both `src/traders.ts` and `src/admin-users.ts` state this in their docstrings — *"the
 * `If-Match` comes from the server, never from arithmetic"* — and until this file **nothing
 * checked it**. A sabotage run found it: replacing the re-read in the suspend handler with
 * `` `"rv-${account.record_version}"` `` left the whole suite green.
 *
 * Why it matters more than it looks. The version in a rendered list is one page old. Sending
 * it back as a precondition means the optimistic-concurrency check compares against what the
 * operator saw when the page loaded, not against what was true when they clicked — so two
 * administrators acting on the same account would both succeed, and the second would
 * silently overwrite the first. The `If-Match` would be present, well-formed and useless,
 * which is the worst of the three available states.
 *
 * **Structural, and deliberately so.** The positive version — driving two concurrent
 * decisions and asserting one gets a 412 — needs a real database and belongs to the
 * integration suite; it is also the version that passes while the client quietly computes a
 * value that happens to be current. Reading the source answers the question directly: does
 * this code construct a precondition, or does it echo one.
 */

const APP_ROOT = join(import.meta.dirname, "..");

function source(...parts: string[]): string {
  return readFileSync(join(APP_ROOT, ...parts), "utf8");
}

/**
 * The same file with its comments removed.
 *
 * Necessary, and the first run proved it: `src/admin-users.ts` explains the rule in prose —
 * *"a screen computing `rv-${n}` itself would be inventing a precondition"* — and the check
 * flagged that sentence as the violation it describes. `test/login.test.ts` records the same
 * lesson from the other direction: a check a prose mention can trip is one somebody
 * eventually satisfies by deleting the explanation, which is the worst possible outcome for
 * a rule whose whole value is that the next person understands it.
 *
 * Block comments then line comments, in that order: a `//` inside a block comment is part of
 * the block, and stripping lines first would leave the block's opener behind.
 */
function code(...parts: string[]): string {
  return source(...parts)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

/**
 * Constructing a version string, as regex **literals**.
 *
 * Not built with `new RegExp` over a template string — inside a template literal `\b` is a
 * backspace rather than a word boundary, which made an earlier structural check in this
 * repository match nothing and pass over any source at all.
 */
const INVENTED_PRECONDITION: readonly RegExp[] = [
  /"rv-\$\{/,
  /`rv-\$\{/,
  /'rv-' ?\+/,
  /"rv-" ?\+/,
  /rv-\$\{[a-zA-Z]/,
] as const;

const WRITING_MODULES = [
  ["src", "admin-users.ts"],
  ["src", "traders.ts"],
  ["app", "admin-users", "page.tsx"],
  ["app", "traders", "page.tsx"],
] as const;

describe("preconditions", () => {
  it("has modules to check, so the assertions below are not vacuous", () => {
    for (const parts of WRITING_MODULES) {
      expect(source(...parts).length, `${parts.join("/")} is empty`).toBeGreaterThan(500);
    }
  });

  it("never constructs an If-Match value", () => {
    for (const parts of WRITING_MODULES) {
      const text = code(...parts);
      for (const pattern of INVENTED_PRECONDITION) {
        expect(text, `${parts.join("/")} builds its own rv- precondition`).not.toMatch(pattern);
      }
    }
  });

  it("still sees the code after the comments are stripped", () => {
    // Guard the guard, second half. If `code()` over-stripped — an unbalanced `*/` in a
    // string, say — it would return almost nothing and the check above would pass over a
    // file it never read.
    for (const parts of WRITING_MODULES) {
      const stripped = code(...parts);
      expect(stripped.length, `${parts.join("/")} was stripped to nothing`).toBeGreaterThan(300);
      // And that the stripping is doing something rather than being a no-op that would let
      // the prose back in.
      expect(stripped.length).toBeLessThan(source(...parts).length);
    }
  });

  it("the patterns actually match a violation", () => {
    // Guard the guard, and it has earned its place twice over in this repository: a
    // structural check whose patterns match nothing passes over exactly the code it was
    // written to refuse.
    const violations = [
      'const ifMatch = `"rv-${account.record_version}"`;',
      "ifMatch: \"rv-\" + trader.record_version,",
      "const tag = 'rv-' + version;",
    ];

    for (const violation of violations) {
      expect(
        INVENTED_PRECONDITION.some((pattern) => pattern.test(violation)),
        `no pattern matches: ${violation}`,
      ).toBe(true);
    }
  });

  it("reads the record again before every write", () => {
    // The positive half. "Constructs nothing" is also true of a screen that sends no
    // precondition at all, which the server would refuse with 428 — a different defect with
    // the same silence.
    const staff = source("app", "admin-users", "page.tsx");
    const traders = source("app", "traders", "page.tsx");

    expect(staff).toContain("await readAdminUser(account.id)");
    expect(traders).toContain("readTrader(");
  });

  it("takes the ETag from the response and refuses to continue without one", () => {
    // The read helpers throw rather than returning undefined when the server sends no
    // ETag. Without that, the next call would have to invent one — which is the failure
    // this whole file exists to prevent, arriving through the back door.
    // `moduleName`, not `module`: Next's `no-assign-module-variable` rule refuses the
    // shorter name because assigning to `module` breaks CommonJS interop in a bundle.
    for (const moduleName of ["admin-users.ts", "traders.ts"]) {
      const text = source("src", moduleName);
      expect(text, `${moduleName} does not read the ETag off the response`).toContain(
        "response.etag",
      );
      expect(text, `${moduleName} continues without an ETag`).toMatch(/throw new Error\(/);
    }
  });
});
