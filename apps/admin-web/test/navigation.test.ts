import { describe, expect, it } from "vitest";

import { adminNavigation } from "../src/navigation";

describe("Admin navigation isolation", () => {
  it("contains internal routes and no Trader-only result publication route", () => {
    const hrefs: readonly string[] = adminNavigation.map(({ href }) => href);

    expect(hrefs).toContain("/audit");
    expect(hrefs).not.toContain("/results");
    expect(hrefs).not.toContain("/profile");
  });
});
