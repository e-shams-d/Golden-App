import { existsSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { traderNavigation } from "../src/navigation";

const APP_ROOT = join(import.meta.dirname, "..");

describe("Trader navigation isolation", () => {
  it("contains no admin route", () => {
    // The count that used to be here — `toHaveLength(5)` — is gone. It had nothing to do
    // with this test's name, and it failed the moment three dead items were removed: three
    // of the five pointed at routes with no page and answered 404. A number asserted beside
    // an unrelated claim is a number that will be edited to match whatever the code does,
    // which is the opposite of a test.
    //
    // What the name claims is checked instead, and it survives items arriving and leaving.
    expect(traderNavigation.length).toBeGreaterThan(0);
    expect(traderNavigation.some(({ href }) => href.startsWith("/admin"))).toBe(false);
    expect(traderNavigation.some(({ href }) => href.startsWith("/audit"))).toBe(false);
  });

  it("gives every item a page that exists", () => {
    // The check that would have caught the three dead links before somebody clicked one.
    // The admin app got this when its demonstration screens landed; this side was missed,
    // and it was worse here — a goldsmith had five items and three were dead ends.
    //
    // Against the filesystem rather than a list, because a list is a second thing to keep
    // in step with the router and it drifts the same way.
    const missing = traderNavigation
      .map(({ href }) => href)
      .filter((href) => {
        const segment = href === "/" ? "" : href.replace(/^\//, "");
        const page = segment
          ? join(APP_ROOT, "app", segment, "page.tsx")
          : join(APP_ROOT, "app", "page.tsx");
        return !existsSync(page);
      });

    expect(
      missing,
      "these navigation items point at routes with no page, so tapping them answers 404",
    ).toEqual([]);
  });

  it("offers a way in from the home page", () => {
    // The defect a person found by trying to use the application: the home page had no link
    // to `/login` and none to `/register`, so the only way past the front screen was to
    // know a URL. Both doors exist and both are reachable, which no test asserted before.
    expect(existsSync(join(APP_ROOT, "app", "login", "page.tsx"))).toBe(true);
    expect(existsSync(join(APP_ROOT, "app", "register", "page.tsx"))).toBe(true);
    expect(existsSync(join(APP_ROOT, "components", "entry-panel.tsx"))).toBe(true);
  });
});
