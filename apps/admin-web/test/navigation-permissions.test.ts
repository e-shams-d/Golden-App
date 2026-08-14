import { readFileSync } from "node:fs";
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
  it("shows the two internal roles different screens, each with something the other lacks", () => {
    // NOT "the administrator sees more". That was the first version of this test and it
    // failed: `business_admin` sees four items and `accountant` sees six.
    //
    // The design is right and the assumption was wrong. Gating on the permission that lets
    // you *act* makes the navigation role-shaped rather than role-ranked: `accountant` is
    // the operational role and holds `manual_review.assign`, `payment_request.review`,
    // `payment_batch.create` and `bank_result_bundle.upload`; `business_admin` is the
    // administrative one and holds `trader.approve` and `source_bank_account.manage`.
    // Neither is a superset of the other, and a seniority ordering does not exist to
    // assert. What the obligation actually claims is that navigation *reflects*
    // permissions, and mutual difference is the honest form of that.
    const administrator = visibleNavigation(adminNavigation, grantsFor("business_admin"));
    const accountant = visibleNavigation(adminNavigation, grantsFor("accountant"));

    const administratorOnly = administrator.filter(
      (item) => !accountant.some((other) => other.href === item.href),
    );
    const accountantOnly = accountant.filter(
      (item) => !administrator.some((other) => other.href === item.href),
    );

    expect(administratorOnly.map((item) => item.href)).toContain("/traders");
    expect(accountantOnly.length, "the accountant sees nothing the administrator does not").
      toBeGreaterThan(0);
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
