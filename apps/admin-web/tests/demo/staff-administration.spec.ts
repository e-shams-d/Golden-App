import { expect, test, type Page } from "@playwright/test";

/**
 * The staff-administration path, in a browser, against the running stack.
 *
 * Slice 8E built ten routes for this — list, create, read, amend, suspend, reactivate,
 * reset, plus the role surface — and **no way to reach any of them**. Everything it proved
 * was proved by a `TestClient`, which is a statement about the API and not about whether an
 * operator can administer their own centre. This is the walk that makes the difference.
 *
 * It also exercises the two refusals that are easiest to build wrongly and hardest to
 * notice: the platform must not let one administrator strand the deployment, and it must
 * not let one lock themselves out. Both arrive as a 400 whose message is written for a
 * person, and the screen renders that message rather than a generic one — so this asserts
 * the *text*, which is the part an operator actually acts on.
 *
 * Run through `infra/scripts/rehearse-demo.sh`, which stands up the stack, builds the
 * frontend images and seeds the first administrator.
 */

const ADMIN = process.env.DEMO_ADMIN_ORIGIN ?? "http://admin.localhost:8080";

const adminUser = process.env.DEMO_ADMIN_USER ?? "";
const adminPassword = process.env.DEMO_ADMIN_PASSWORD ?? "";

const NEW_USERNAME = `demo_accountant_${Date.now().toString().slice(-6)}`;

/**
 * The account cards, scoped to their own section.
 *
 * A bare `page.locator("li")` also matches the navigation's items and, on the roles screen,
 * every permission code — and the first run of this file failed on exactly that. Scoping to
 * the section makes the locator mean "an account", which is what every assertion below is
 * about.
 */
const accountCards = (page: Page) =>
  page.locator("section[aria-labelledby='accounts-heading'] li");

test.describe("staff administration", () => {
  test.skip(!adminUser, "run through infra/scripts/rehearse-demo.sh");

  test("an administrator creates, suspends and reactivates a colleague", async ({ page }) => {
    await test.step("sign in and reach the screen from the navigation", async () => {
      await page.goto(`${ADMIN}/login`);
      await page.getByLabel(/نام کاربری/).fill(adminUser);
      await page.getByLabel(/گذرواژه/).fill(adminPassword);
      await page.getByRole("button", { name: "ورود", exact: true }).click();
      await page.waitForURL(`${ADMIN}/`);

      // Through the menu, not by typing the URL. The navigation is permission-gated now,
      // so this also proves `user.read` reached the browser from `/auth/me`.
      await page.getByRole("link", { name: "کارکنان" }).click();
      await page.waitForURL(`${ADMIN}/admin-users`);
      await expect(page.getByRole("heading", { level: 1, name: /مدیریت کارکنان/ })).toBeVisible();
    });

    await test.step("the bootstrap administrator is listed", async () => {
      // The floor. Everything below is about a second account; without the first being
      // visible, "the list works" would be a claim about an empty page.
      await expect(accountCards(page).filter({ hasText: adminUser })).toBeVisible({
        timeout: 15_000,
      });
    });

    await test.step("create an account", async () => {
      await page.getByLabel("نام کاربری").fill(NEW_USERNAME);
      await page.getByLabel("نام و نام خانوادگی").fill("همکار نمونه");
      await page.getByLabel("گذرواژهٔ اولیه").fill("Colleague-initial-password-1");
      await page.getByLabel("نقش").selectOption("accountant");
      await page.getByRole("button", { name: "ساخت حساب" }).click();

      await expect(page.getByText(new RegExp(`حساب ${NEW_USERNAME} ساخته شد`))).toBeVisible({
        timeout: 15_000,
      });
      // Scoped to the list, not the whole page. `getByText(NEW_USERNAME)` matched two
      // elements — the success notice above and the new card — and Playwright's strict mode
      // refused it. Loosening to `.first()` would have hidden which one it found; scoping
      // says the account is in the *list*, which is the claim.
      await expect(accountCards(page).filter({ hasText: NEW_USERNAME })).toBeVisible();
    });

    await test.step("suspend it, and the screen says the sessions ended", async () => {
      const card = accountCards(page).filter({ hasText: NEW_USERNAME });
      await card.getByRole("button", { name: "تعلیق" }).click();

      await expect(page.getByText(/حساب معلق شد/)).toBeVisible({ timeout: 15_000 });
      await expect(card.getByText("معلق")).toBeVisible();
    });

    await test.step("reactivate it", async () => {
      const card = accountCards(page).filter({ hasText: NEW_USERNAME });
      await card.getByRole("button", { name: "فعال‌سازی دوباره" }).click();

      await expect(page.getByText(/حساب دوباره فعال شد/)).toBeVisible({ timeout: 15_000 });
      await expect(card.getByText("فعال", { exact: true })).toBeVisible();
    });
  });

  test("the platform refuses to let an administrator strand or lock out itself", async ({
    page,
  }) => {
    await page.goto(`${ADMIN}/login`);
    await page.getByLabel(/نام کاربری/).fill(adminUser);
    await page.getByLabel(/گذرواژه/).fill(adminPassword);
    await page.getByRole("button", { name: "ورود", exact: true }).click();
    // Wait for the login to land before navigating. Without this, `goto` races the
    // redirect and can arrive before the session cookie is in the jar — which the first
    // run of this file did, and it surfaced as "element(s) not found" on a page that had
    // simply rendered its signed-out state.
    await page.waitForURL(`${ADMIN}/`);
    await page.goto(`${ADMIN}/admin-users`);

    const own = accountCards(page).filter({ hasText: adminUser });
    await expect(own).toBeVisible({ timeout: 15_000 });

    await test.step("suspending the last administrator is refused, with the reason", async () => {
      await own.getByRole("button", { name: "تعلیق" }).click();

      // The server's own message, rendered rather than replaced. An operator who is told
      // only "that failed" cannot act; one told which account to grant first, can.
      await expect(page.getByText(/last active account/)).toBeVisible({ timeout: 15_000 });
    });

    await test.step("and so is resetting one's own credential", async () => {
      await page.reload();
      const self = accountCards(page).filter({ hasText: adminUser });
      await self.getByRole("button", { name: "بازنشانی گذرواژه" }).click();

      await expect(page.getByText(/change-password/)).toBeVisible({ timeout: 15_000 });
    });
  });

  test("the roles screen shows why a menu differs", async ({ page }) => {
    await page.goto(`${ADMIN}/login`);
    await page.getByLabel(/نام کاربری/).fill(adminUser);
    await page.getByLabel(/گذرواژه/).fill(adminPassword);
    await page.getByRole("button", { name: "ورود", exact: true }).click();
    await page.waitForURL(`${ADMIN}/`);

    await page.getByRole("link", { name: "نقش‌ها و دسترسی‌ها" }).click();
    await page.waitForURL(`${ADMIN}/roles`);

    await expect(page.getByRole("heading", { level: 2, name: "business_admin" })).toBeVisible({
      timeout: 15_000,
    });
    // The permission that decides whether the traders item appears, shown where somebody can
    // point at it. This is what makes the role-aware navigation explicable in a demo rather
    // than merely observable.
    await expect(page.getByText("trader.approve").first()).toBeVisible();
    await expect(page.getByText(/تعداد مجوزها: \d+/).first()).toBeVisible();
  });
});
