import { describe, expect, it } from "vitest";

import { adminNavigation } from "../src/navigation";

describe("Admin navigation isolation", () => {
  it("contains internal routes and no Trader-only result publication route", () => {
    const hrefs: readonly string[] = adminNavigation.map(({ href }) => href);

    // `/audit` until the demo-screens slice, which removed every item whose page does not
    // exist — clicking six of the eight answered 404. `/traders` is the replacement anchor:
    // it is an internal route, its page exists, and it is not going away. The audit item
    // returns with the milestone that builds its screen.
    expect(hrefs).toContain("/traders");
    // The claim this test is actually about, unchanged: the trader app's routes are not in
    // the admin bundle's navigation.
    expect(hrefs).not.toContain("/results");
    expect(hrefs).not.toContain("/profile");
  });
});
