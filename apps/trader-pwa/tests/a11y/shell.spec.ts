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
  // M5 slice 8's screens. Added with them, because the note above `/profile` describes exactly
  // what would otherwise have happened: `pnpm check` went green over three new screens this
  // sweep never visited, and the `/states/[kind]` page's own comment predicts the shape of it —
  // a surface outside this fixed list is a surface nobody checks.
  //
  // Against no backend each renders its failure or empty state, which is the state worth
  // holding to the standard: it is the one a person meets when something is wrong, and the one
  // most likely to be built without a heading or a live region.
  "/requests",
  "/requests/new",
  "/beneficiaries",
  // M11 Screens slice 1. The notification list, in the sweep from the moment it exists.
  //
  // `TRACE-SCREENS-001` was written as "compare the sweep against the routes that exist"
  // rather than "the screens this plan adds", and that is the only reason it caught
  // `/login` being unswept since M3. A new page that is not added here fails it immediately,
  // which is the intent: the sweep is a list of what a person can open, not of what somebody
  // remembered.
  "/notifications",
  // M11 Screens slice 3. The published payment result.
  //
  // A concrete path rather than relying on the `/requests` prefix: this is a separate page
  // with its own headings and controls, and a prefix match is the compromise that lets one
  // entry stand for a family of dynamic routes — not evidence that each was opened.
  //
  // The id is obviously fake, so the page renders the state a person reaches by following a
  // stale link. `apps/trader-pwa/test/screens-are-swept.test.ts` is what now compares this
  // list against the routes that exist; until slice 3 only `admin-web` had that gate.
  "/requests/00000000-0000-4000-8000-000000000001/result",
  // M11 Screens slice 3 found these three unswept, by porting `TRACE-SCREENS-001`'s
  // sweep-versus-routes comparison to this application — until then it existed only for
  // `admin-web`, which is why the obligation's own history records it catching *that* app's
  // `/login` and never this one.
  //
  // `/login` is the screen every trader must use before any other. `/evidence` is reached
  // from a request. `/offline` is what a PWA shows when the network is gone, which is a
  // state this audience hits on a phone rather than an edge case.
  "/login",
  "/evidence",
  "/offline",
  // M11 Screens slice 5. The trader's gold orders: the list with its inline new-order
  // form, and one order by a fake id, which renders the failure state somebody reaches
  // by following a stale link.
  "/gold-orders",
  "/gold-orders/00000000-0000-4000-8000-000000000006",
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
