import { expect, test } from "@playwright/test";

/**
 * What a session changes, and what it cannot reach — against the running stack.
 *
 * Two obligations that could not be written before slice 10D, for the same reason: nothing
 * in either app ever called `GET /auth/me`. `adminAuthAdapter` was exported and imported
 * nowhere, the shell rendered a literal "role unknown", and an authenticated administrator
 * and an anonymous visitor produced identical bytes. There was no difference to assert.
 *
 * WHY THIS IS IN THE DEMO SUITE AND NOT THE ACCESSIBILITY ONE. Both claims need the compose
 * stack: the first needs a real session cookie from a real login, and the second needs the
 * deployment's two hostnames — `admin.localhost` and `trader.localhost` — which only nginx
 * serves. `infra/scripts/rehearse-demo.sh` is the entry point, and it now builds the
 * frontend images rather than using whatever is on disk, because a run against a stale
 * image proves the previous commit works.
 *
 * Covers: UI-LOGIN-001, UI-ISO-002.
 */

const ADMIN = process.env.DEMO_ADMIN_ORIGIN ?? "http://admin.localhost:8080";
const TRADER = process.env.DEMO_TRADER_ORIGIN ?? "http://trader.localhost:8080";

const phone = process.env.DEMO_PHONE ?? "";
const traderPassword = process.env.DEMO_TRADER_PASSWORD ?? "";
const adminUser = process.env.DEMO_ADMIN_USER ?? "";
const adminPassword = process.env.DEMO_ADMIN_PASSWORD ?? "";

test.describe("the landing surface and audience isolation", () => {
  test.skip(
    !phone || !adminUser,
    "run through infra/scripts/rehearse-demo.sh, which stands up the stack and seeds the identities",
  );

  test("signing in lands on a surface an anonymous visitor does not render", async ({
    page,
    browser,
  }) => {
    // UI-LOGIN-001. The negative half first, and from a *separate context*: asserting the
    // absence after a sign-in would prove nothing, because the panel would simply not have
    // rendered yet.
    const anonymous = await browser.newContext();
    const visitor = await anonymous.newPage();
    await visitor.goto(`${ADMIN}/`);
    await expect(
      visitor.getByRole("heading", { name: /برای ادامه وارد شوید/ }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(visitor.getByRole("heading", { name: /شما وارد شده‌اید/ })).toHaveCount(0);
    await anonymous.close();

    await page.goto(`${ADMIN}/login`);
    await page.getByLabel(/نام کاربری/).fill(adminUser);
    await page.getByLabel(/گذرواژه/).fill(adminPassword);
    await page.getByRole("button", { name: "ورود", exact: true }).click();
    await page.waitForURL(`${ADMIN}/`);

    // The positive half. A heading rather than a class name or a colour: an assertion on
    // styling would pass over a page that told the person nothing.
    await expect(page.getByRole("heading", { name: /شما وارد شده‌اید/ })).toBeVisible({
      timeout: 15_000,
    });
    // And the count, which is what makes the surface session-*derived* rather than merely
    // a second static panel behind a login.
    await expect(page.getByText(/تعداد دسترسی‌های فعال: \d+/)).toBeVisible();
  });

  test("navigation reflects the session, and the server still refuses what it hides", async ({
    page,
  }) => {
    // The frontend half of UI-NAV-001 against the real deployment. The unit test proves the
    // filter; this proves the filter is wired to a real `/auth/me` response, which is the
    // part that had no caller at all.
    await page.goto(`${ADMIN}/`);
    const navigation = page.getByRole("navigation", { name: "ناوبری عملیات داخلی" });
    // Anonymous: only the dashboard, which carries no permission.
    await expect(navigation.getByRole("link")).toHaveCount(1);

    await page.goto(`${ADMIN}/login`);
    await page.getByLabel(/نام کاربری/).fill(adminUser);
    await page.getByLabel(/گذرواژه/).fill(adminPassword);
    await page.getByRole("button", { name: "ورود", exact: true }).click();
    await page.waitForURL(`${ADMIN}/`);

    // `business_admin` holds `trader.approve`, so the traders item appears. Asserted as
    // "more than one" plus the specific item, because a count alone would pass if the
    // filter had stopped filtering and shown everything.
    await expect(navigation.getByRole("link", { name: "طلافروشان" })).toBeVisible({
      timeout: 15_000,
    });
    const links = await navigation.getByRole("link").count();
    expect(links).toBeGreaterThan(1);
    expect(links).toBeLessThan(9);
  });

  test("a trader session cannot reach the centre's surface, and can reach its own", async ({
    browser,
  }) => {
    // UI-ISO-002, end to end. Three assertions in a fixed order, and the order is the test.
    const context = await browser.newContext();
    const traderPage = await context.newPage();

    await traderPage.goto(`${TRADER}/login`);
    await traderPage.getByLabel(/شماره موبایل/).fill(phone);
    await traderPage.getByLabel(/گذرواژه/).fill(traderPassword);
    await traderPage.getByRole("button", { name: "ورود", exact: true }).click();
    await traderPage.waitForURL(`${TRADER}/`);

    // FIRST: the cookie is in the jar. Without this the refusal below would be satisfied by
    // nobody being logged in at all, which is the most comfortable green available here.
    const session = (await context.cookies()).find(
      (cookie) => cookie.name === "__Host-gp_trader_session",
    );
    expect(session, "no trader session cookie was stored, so nothing was isolated").toBeTruthy();
    expect(session?.domain).toBe(new URL(TRADER).hostname);

    // SECOND: the positive control on the trader's own host. A 401 that also appears on the
    // caller's own origin proves nothing about isolation — it proves the session is broken.
    const own = await traderPage.goto(`${TRADER}/api/v1/me/trader/profile`);
    expect(own?.status(), "the trader cannot reach its own surface either").toBe(200);

    // THIRD: the centre's host refuses. Navigated by the browser rather than through
    // Playwright's APIRequestContext, which resolves hostnames with Node's resolver and has
    // no entry for `*.localhost`; Chromium maps those names to loopback itself.
    const centre = await traderPage.goto(`${ADMIN}/api/v1/traders`);
    expect(
      [401, 403],
      "a browser holding a working trader session reached the centre's list",
    ).toContain(centre?.status() ?? 0);

    await context.close();
  });
});
