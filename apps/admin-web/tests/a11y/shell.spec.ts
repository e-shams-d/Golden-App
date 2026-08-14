import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const paths = [
  "/",
  "/states/loading",
  "/states/error",
  "/states/empty",
  "/states/forbidden",
  "/states/conflict",
  // The three kinds slice 10C added. Listed here and not derived from `STATE_KINDS`
  // deliberately: this file is the check, and a check that iterated the same list the
  // pages are generated from would pass over a kind that renders nothing at all.
  "/states/precondition",
  "/states/idempotency",
  "/states/timeout",
  // The approval screen, added with the screen rather than after it. This suite keeps a
  // fixed list precisely so a new page is a visible edit rather than an oversight — a
  // screen outside the list is a screen nobody checks.
  //
  // It renders here against no backend, so what is asserted is its failure state. That is
  // the state most likely to ship without a heading or without an announced region, and
  // it is the one an operator sees on the worst day.
  "/traders",
] as const;

for (const path of paths) {
  test(`Admin shell accessibility smoke: ${path}`, async ({ page }) => {
    await page.goto(path);

    await expect(page.locator("html")).toHaveAttribute("lang", "fa");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });
}
