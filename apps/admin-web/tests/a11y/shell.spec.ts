import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const paths = [
  "/",
  // Added by screens slice 4, because `TRACE-SCREENS-001` found them missing the moment it was
  // written. Neither belongs to the screens plan — which is the point: the obligation compares the
  // list against the routes that *exist*, and softening it to "the screens this plan added" would
  // have left the first page every operator sees unchecked since M3.
  //
  // `/login` is that page. `/requests/[requestId]` arrived with M5 slice 8 and was the one route of
  // that slice nobody swept.
  "/login",
  "/requests/00000000-0000-4000-8000-000000000003",
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
  // The two screens that finally give slice 8E's ten routes a way to be reached. Added with
  // the screens rather than after them — this suite keeps a fixed list precisely so a new
  // page is a visible edit, and against no backend both render their failure state, which
  // is the one an operator meets on the worst day.
  "/admin-users",
  "/roles",
  // M5 slice 8. The accountant's queue, added with it for the reason stated twice above — and
  // the reason is not theoretical here: `pnpm check` passed on this branch before this line
  // existed, over a screen the sweep had never opened.
  "/requests",
  // M7 screens slice 1. The approval queue and one version's detail, added with them for the
  // reason stated three times above. The detail path uses obviously-fake ids: against no backend
  // it renders its "not found" state, which is a real state a manager reaches by following a
  // stale link — and it is the state most likely to ship without a heading.
  "/batches",
  "/batches/00000000-0000-4000-8000-000000000000/versions/00000000-0000-4000-8000-000000000001",
  // M7 screens slice 3. The bank file, added with it for the reason stated four times above. A
  // fake id again, so this opens the "not found" state — and here that state matters more than
  // most: somebody following a link to an export that was voided and replaced lands on exactly
  // this page, and they need to be told which of the two things happened.
  "/bank-exports/00000000-0000-4000-8000-000000000002",
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
