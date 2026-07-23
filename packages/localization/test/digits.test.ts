import { describe, expect, it } from "vitest";

import { normalizeDigits, toPersianDigits } from "../src";

describe("digit normalization", () => {
  it("accepts Persian, Arabic and Latin digits without precision conversion", () => {
    expect(normalizeDigits("۱۲۳-٤٥٦-789")).toBe("123-456-789");
    expect(toPersianDigits("100000000000000000001")).toBe(
      "۱۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۱",
    );
  });
});
