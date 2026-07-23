import { describe, expect, it } from "vitest";

import { traderNavigation } from "../src/navigation";

describe("Trader navigation isolation", () => {
  it("contains no admin route", () => {
    expect(traderNavigation).toHaveLength(5);
    expect(traderNavigation.some(({ href }) => href.startsWith("/admin"))).toBe(false);
    expect(traderNavigation.some(({ href }) => href.startsWith("/audit"))).toBe(false);
  });
});
