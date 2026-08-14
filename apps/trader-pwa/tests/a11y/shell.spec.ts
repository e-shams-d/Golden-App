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
  // pages are generated from would pass over a kind that renders nothing.
  "/states/precondition",
  "/states/idempotency",
  "/states/timeout",
  // The business's own account screen, added with the screen for the same reason the
  // admin list is: a page outside this fixed list is a page nobody checks. Against no
  // backend it renders its failure state, which is the one worth holding to the standard.
  "/profile",
  // Applying. The one screen in this app a person reaches before they have any account at
  // all — so it is the one most likely to be met by somebody who has never seen the
  // platform, on whatever phone they own. Six labelled fields, their hints and their
  // objections is also the largest amount of form this app has anywhere.
  "/register",
] as const;

for (const path of paths) {
  test(`Trader shell accessibility smoke: ${path}`, async ({ page }) => {
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
