import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { visibleNavigation, type NavigationItem } from "@gold/ui";
import { describe, expect, it } from "vitest";

import { adminNavigation } from "../src/navigation";

/**
 * The module is `as const satisfies readonly NavigationItem[]`, so its type is a union of
 * literal object shapes — and the dashboard entry carries no `permission` key at all, which
 * makes `item.permission` a type error on the union. Widened here rather than in the
 * module: the literal `href` types are useful to callers, and `exactOptionalPropertyTypes`
 * means adding `permission: undefined` to the dashboard would not be assignable anyway.
 */
const items: readonly NavigationItem[] = adminNavigation;

/**
 * Navigation reflects permissions — the first half of `UI-NAV-001`.
 *
 * The second half lives in `tests/integration/test_navigation_is_not_a_control.py`, and it
 * is the one that matters: a hidden item is not a denial, and the route it points at must
 * still refuse the call when somebody types the URL. Splitting them across two suites is
 * deliberate — the half that proves the frontend is *not* the control cannot be written in
 * the frontend.
 *
 * **The gating permission is the one that lets you act, not the one that lets you read.**
 * That is an owner decision recorded during slice 10D, and the reason it had to be a
 * decision is asserted below: `accountant` holds a read permission behind every item, so a
 * read-gated navigation would hide nothing from the only unprivileged internal role that
 * exists — and this test would have been written against a permission nobody is granted.
 *
 * Covers: UI-NAV-001.
 */

const REPOSITORY_ROOT = join(import.meta.dirname, "..", "..", "..");
const CATALOGUE = join(REPOSITORY_ROOT, "docs", "governance", "permission_catalog.yaml");

/**
 * What a seeded role holds, parsed from the approved catalogue.
 *
 * From the catalogue rather than from a list in this file: a test that granted its own
 * permissions would prove the filter reads *a* set, not that the seeded roles differ in the
 * way the navigation assumes.
 */
function grantsFor(role: string): string[] {
  const text = readFileSync(CATALOGUE, "utf8");
  const entries = [
    ...text.matchAll(/^ {6}([a-z_]+\.[a-z_]+):\n(?:[ ]{8}.*\n)*?[ ]{8}default_roles: \[([^\]]*)\]/gm),
  ];
  return entries
    .filter(([, , roles]) => roles!.split(",").some((name) => name.trim() === role))
    .map(([, code]) => code!);
}

describe("what the catalogue actually grants", () => {
  it("parses a plausible number of grants, so the checks below are not vacuous", () => {
    // Guard the guard. A pattern that stopped matching would return nothing, and
    // "accountant sees only the ungated items" would then be true for the wrong reason.
    expect(grantsFor("accountant").length).toBeGreaterThan(40);
    expect(grantsFor("business_admin").length).toBeGreaterThan(20);
  });

  it("confirms the reason read-gating was rejected", () => {
    // The finding that turned this into an owner decision. If this ever stops being true,
    // the navigation design should be revisited rather than left as an unexplained choice.
    const accountant = new Set(grantsFor("accountant"));

    for (const code of ["trader.read", "audit.read", "payment_request.read"]) {
      expect(accountant.has(code), `${code} is no longer held by accountant`).toBe(true);
    }
    // And that it holds none of the action permissions the navigation gates on.
    expect(accountant.has("trader.approve")).toBe(false);
    expect(accountant.has("source_bank_account.manage")).toBe(false);
  });
});

describe("the navigation a role sees", () => {
  it("shows the two internal roles different navigations", () => {
    // Difference, and deliberately not an ordering — this assertion has now been wrong in
    // both directions and the history is why it is written this way.
    //
    // The first version said the administrator sees *more*, and failed: with all eight
    // items, `business_admin` saw four and `accountant` six, because gating on actions
    // makes the navigation role-shaped rather than role-ranked. The second said each role
    // sees something the other lacks, and failed once the demo-screens slice removed every
    // item whose page did not exist — the four that remain are all administrative, so
    // `business_admin` is a superset again.
    //
    // Both failures were the test's assumption and not the design. The obligation claims
    // navigation *reflects* permissions; the durable form of that is that two roles with
    // different grants get different menus, which survives screens arriving and leaving.
    const administrator = visibleNavigation(adminNavigation, grantsFor("business_admin"));
    const accountant = visibleNavigation(adminNavigation, grantsFor("accountant"));

    const administratorHrefs = administrator.map((item) => item.href);
    const accountantHrefs = accountant.map((item) => item.href);

    expect(administratorHrefs).not.toEqual(accountantHrefs);
    // Anchored on a specific item, because "the two arrays differ" is also satisfied by a
    // filter that has started returning nonsense.
    expect(administratorHrefs).toContain("/traders");
    expect(accountantHrefs).not.toContain("/traders");
  });

  it("hides every administrative screen from the operational role", () => {
    // Named item by item rather than as a count. The sabotage run found the weakness: the
    // list-level check below asks only that *some* item discriminates, so re-gating the
    // staff screen on `audit.read` — which `accountant` holds — hid nothing new and the
    // suite stayed green. The demo's claim is about these three specifically.
    const accountant = visibleNavigation(adminNavigation, grantsFor("accountant")).map(
      (item) => item.href,
    );
    const administrator = visibleNavigation(adminNavigation, grantsFor("business_admin")).map(
      (item) => item.href,
    );

    for (const href of ["/traders", "/admin-users", "/roles"]) {
      expect(accountant, `${href} is visible to the operational role`).not.toContain(href);
      // Paired every time. "Absent from the accountant's menu" is also satisfied by an item
      // nobody sees, which is what a gate on a non-existent permission produces.
      expect(administrator, `${href} is visible to nobody`).toContain(href);
    }
  });

  it("hides the traders screen from a role that cannot approve one", () => {
    const accountant = visibleNavigation(adminNavigation, grantsFor("accountant"));
    const administrator = visibleNavigation(adminNavigation, grantsFor("business_admin"));

    expect(accountant.map((item) => item.href)).not.toContain("/traders");
    // Paired with the positive half. "Does not contain /traders" is also satisfied by an
    // empty navigation, which is the failure mode of a filter that has stopped working.
    expect(administrator.map((item) => item.href)).toContain("/traders");
  });

  it("shows an anonymous visitor only the items that carry no permission", () => {
    const anonymous = visibleNavigation(adminNavigation, []);

    expect(anonymous.map((item) => item.href)).toEqual(["/"]);
    // Not empty, deliberately: an empty sidebar is indistinguishable from a failed load,
    // and the dashboard is what an authenticated person lands on anyway.
    expect(anonymous.length).toBeGreaterThan(0);
  });

  it("shows every item to a caller holding everything", () => {
    const everything = items
      .map((item) => item.permission)
      .filter((permission): permission is string => permission !== undefined);

    expect(visibleNavigation(adminNavigation, everything).length).toBe(adminNavigation.length);
  });
});

describe("where the navigation actually goes", () => {
  it("gives every item a page that exists", () => {
    // The gate that would have caught this before a demo. Six of the eight items pointed at
    // routes with no `page.tsx` at all, so clicking them answered 404 — and the
    // permission-gated menu shipped in slice 10D made it read as a working menu rather than
    // a placeholder one, which is worse.
    //
    // Checked against the filesystem rather than against a list, because a list would be a
    // second thing to keep in step with the router and would drift the same way.
    const missing = items
      .map((item) => item.href)
      .filter((href) => {
        const segment = href === "/" ? "" : href.replace(/^\//, "");
        const page = segment
          ? join(REPOSITORY_ROOT, "apps", "admin-web", "app", segment, "page.tsx")
          : join(REPOSITORY_ROOT, "apps", "admin-web", "app", "page.tsx");
        return !existsSync(page);
      });

    expect(
      missing,
      "these navigation items point at routes with no page, so clicking them answers 404",
    ).toEqual([]);
  });

  it("has items to check, so the filesystem check above is not vacuous", () => {
    expect(items.length).toBeGreaterThanOrEqual(3);
  });
});

describe("the gating permissions themselves", () => {
  it("names only permissions the approved catalogue defines", () => {
    // A gate on a permission that does not exist hides the item from everybody, and it
    // hides it silently — the filter simply never matches.
    const catalogue = readFileSync(CATALOGUE, "utf8");

    for (const item of items) {
      if (item.permission === undefined) continue;
      expect(catalogue, `${item.permission} is not in the approved catalogue`).toContain(
        `      ${item.permission}:`,
      );
    }
  });

  it("gates every item except the dashboard", () => {
    // The dashboard is the landing surface and carries none by design. Anything else
    // ungated would be a screen shown to everybody, which is the state this slice replaced.
    const ungated = items.filter((item) => item.permission === undefined);

    expect(ungated.map((item) => item.href)).toEqual(["/"]);
  });

  it("gates on a permission at least one seeded role does not hold", () => {
    // The check that would have caught the naive design. A gate everybody satisfies is a
    // gate that hides nothing, and the test asserting navigation reflects permissions would
    // pass while proving nothing at all.
    const accountant = new Set(grantsFor("accountant"));
    const discriminating = items.filter(
      (item) => item.permission !== undefined && !accountant.has(item.permission),
    );

    expect(
      discriminating.length,
      "no navigation item is gated on a permission the unprivileged seeded role lacks",
    ).toBeGreaterThan(0);
  });
});
