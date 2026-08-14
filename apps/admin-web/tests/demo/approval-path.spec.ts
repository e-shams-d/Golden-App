import { expect, test, type Page } from "@playwright/test";

/**
 * The whole onboarding path, driven through both interfaces against the running stack.
 *
 * This is the rehearsal, not a unit of the suite. Everything else in this repository
 * tests a part: this drives nginx, two Next.js servers, the API, PostgreSQL and Redis in
 * one sitting, as a person would. It is deliberately **not** in the default check chain —
 * it needs a compose stack that a developer machine may not have running — and
 * `infra/scripts/rehearse-demo.sh` is what stands that stack up and calls it.
 *
 * WHY A BROWSER RATHER THAN curl. The session cookie carries the `__Host-` prefix, and
 * curl refuses to store a prefixed cookie received over plain HTTP. Chromium stores and
 * sends it because it treats `localhost` and `*.localhost` as trustworthy origins — which
 * this milestone measured rather than assumed. Two hours of a curl harness returning 401
 * is the reason that sentence is written here.
 *
 * THE REGISTRATION IS THE FIRST STEP NOW. It used to be a `curl` inside the script,
 * carrying a comment that said pretending otherwise would hide the one manual step a
 * demonstration still had. Slice D4 built the screen, so the walk starts where a goldsmith
 * starts — and the run no longer depends on any HTTP client but the browser.
 *
 * WHAT IT DOES NOT PROVE. It signs in through both real forms and lands on each app's
 * root, which is a static shell today; it says nothing about role-aware navigation or a
 * session-derived dashboard, and those obligations stay owned by their own slice. The ids
 * are deliberately not written here, because the traceability scanner counts any
 * obligation id in a test file as coverage — so a sentence explaining that something is
 * deferred would register as proof that it is done.
 *
 * Covers: OPS-DEMO-001.
 */

const ADMIN = process.env.DEMO_ADMIN_ORIGIN ?? "http://admin.localhost:8080";
const TRADER = process.env.DEMO_TRADER_ORIGIN ?? "http://trader.localhost:8080";

const phone = process.env.DEMO_PHONE ?? "";
const traderPassword = process.env.DEMO_TRADER_PASSWORD ?? "";
const adminUser = process.env.DEMO_ADMIN_USER ?? "";
const adminPassword = process.env.DEMO_ADMIN_PASSWORD ?? "";
const businessName = process.env.DEMO_BUSINESS_NAME ?? "طلافروشی نمونه";

/**
 * The approval screen's row for the business this walk registered.
 *
 * A table row rather than the page, because the seeded deployment holds nine other
 * businesses and three of them are also awaiting a decision. Every assertion about "the
 * pending application" has to name which one, or it is an assertion about whichever row
 * the server happened to return first.
 */
const applicantRow = (page: Page) =>
  page.locator("tr").filter({ hasText: businessName });

test("the centre approves a goldsmith, and the goldsmith sees the decision", async ({
  page,
  browser,
}) => {
  // Skipped rather than failed when run outside the harness: the identities are created by
  // the script, and a bare `pnpm exec playwright test` should say why it did nothing.
  test.skip(
    !phone || !adminUser,
    "run through infra/scripts/rehearse-demo.sh, which stands up the stack and seeds the identities",
  );

  await test.step("a goldsmith applies through the registration screen", async () => {
    const context = await browser.newContext();
    const applicant = await context.newPage();
    await applicant.goto(`${TRADER}/register`);
    await expect(applicant.getByRole("heading", { level: 1, name: /درخواست همکاری/ })).toBeVisible();

    await applicant.getByLabel("نام کسب‌وکار").fill(businessName);
    await applicant.getByLabel("نام و نام خانوادگی مسئول").fill("مالک نمونه");
    await applicant.getByLabel("شماره موبایل").fill(phone);
    await applicant.getByLabel("گذرواژه", { exact: true }).fill(traderPassword);
    await applicant.getByLabel("تکرار گذرواژه").fill(traderPassword);
    await applicant.getByRole("button", { name: "ثبت درخواست" }).click();

    await expect(applicant.getByRole("heading", { name: /درخواست شما دریافت شد/ })).toBeVisible({
      timeout: 15_000,
    });
    // A fresh context, thrown away: an applicant has no session, and reusing this one for
    // the administrator would let a cookie set here decide a later step.
    await context.close();
  });

  await test.step("the administrator signs in through the real form", async () => {
    await page.goto(`${ADMIN}/login`);
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await page.getByLabel(/نام کاربری/).fill(adminUser);
    await page.getByLabel(/گذرواژه/).fill(adminPassword);
    await page.getByRole("button", { name: "ورود", exact: true }).click();
    await page.waitForURL(`${ADMIN}/`);
  });

  await test.step("the session cookie is host-only and Secure", async () => {
    const session = (await page.context().cookies()).find(
      (cookie) => cookie.name === "__Host-gp_admin_session",
    );
    expect(session, "no admin session cookie was stored").toBeTruthy();
    // The two attributes the `__Host-` prefix forces, asserted because they are what keep
    // this credential off the sibling host — not decoration.
    expect(session?.secure).toBe(true);
    expect(session?.domain).toBe(new URL(ADMIN).hostname);
  });

  await test.step("the pending application is on the approval screen", async () => {
    await page.goto(`${ADMIN}/traders`);
    await expect(page.getByRole("heading", { level: 1, name: /طلافروشان/ })).toBeVisible();
    // Scoped to this business's own row. `.first()` was correct only while the deployment
    // held exactly one business, and seeding nine of them showed what that assumption was
    // worth: the click landed on somebody else's application, the approval succeeded, the
    // "تأییدشده" assertion passed on the wrong row, and the failure surfaced three steps
    // later as the goldsmith not seeing a decision that was never made about them.
    //
    // The demonstration is the reason to fix it rather than loosen it: an operator's screen
    // has many rows, and a test that only works against one is not testing the screen.
    await expect(applicantRow(page)).toBeVisible();
    await expect(applicantRow(page).getByText("در انتظار تأیید")).toBeVisible();
  });

  await test.step("the centre approves, and sees its own decision", async () => {
    await applicantRow(page).getByRole("button", { name: "تأیید", exact: true }).click();
    // The list refreshes from the server rather than mutating in place, so this also
    // asserts the decision reached the database and came back — and it is asserted on this
    // business's row, so a decision applied to a different one cannot satisfy it.
    await expect(applicantRow(page).getByText("تأییدشده")).toBeVisible({ timeout: 15_000 });
  });

  await test.step("the goldsmith signs in on its own host and sees the decision", async () => {
    const context = await browser.newContext();
    const traderPage = await context.newPage();
    await traderPage.goto(`${TRADER}/login`);
    await traderPage.getByLabel(/شماره موبایل/).fill(phone);
    await traderPage.getByLabel(/گذرواژه/).fill(traderPassword);
    await traderPage.getByRole("button", { name: "ورود", exact: true }).click();
    await traderPage.waitForURL(`${TRADER}/`);

    await traderPage.goto(`${TRADER}/profile`);
    await expect(
      traderPage.getByRole("heading", { name: /کسب‌وکار شما تأیید شد/ }),
    ).toBeVisible({ timeout: 15_000 });
    await context.close();
  });

  await test.step("a trader session cannot reach the centre's surface", async () => {
    const context = await browser.newContext();
    const traderPage = await context.newPage();
    await traderPage.goto(`${TRADER}/login`);
    await traderPage.getByLabel(/شماره موبایل/).fill(phone);
    await traderPage.getByLabel(/گذرواژه/).fill(traderPassword);
    await traderPage.getByRole("button", { name: "ورود", exact: true }).click();
    await traderPage.waitForURL(`${TRADER}/`);

    // Navigated by the browser, not through Playwright's APIRequestContext: that resolves
    // hostnames with Node's resolver, which has no entry for `*.localhost` and fails with
    // EAI_AGAIN. Chromium maps those names to loopback itself — which is also why this
    // deployment can use two hostnames without anybody editing /etc/hosts.
    const response = await traderPage.goto(`${ADMIN}/api/v1/traders`);
    expect(
      [401, 403],
      "a browser holding only a trader session reached the centre's list",
    ).toContain(response?.status() ?? 0);
    await context.close();
  });
});
