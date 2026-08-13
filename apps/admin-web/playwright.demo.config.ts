import { defineConfig, devices } from "@playwright/test";

/**
 * The demonstration rehearsal: both interfaces against a running compose stack.
 *
 * Separate from `playwright.config.ts` (accessibility, one app, its own server) and from
 * `playwright.platform.config.ts` (browser contracts, no application at all). This one
 * needs the whole stack, so it has **no `webServer`** — starting one here would serve a
 * single app on a port and hide the fact that the thing under test is the deployment.
 *
 * `infra/scripts/rehearse-demo.sh` is the entry point. Running this config on its own
 * skips with a message rather than failing, because without the script there are no
 * identities to sign in as.
 */

const chromiumExecutablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
const outputDirectory = process.env.PLAYWRIGHT_OUTPUT_DIR;

export default defineConfig({
  ...(outputDirectory ? { outputDir: outputDirectory } : {}),
  testDir: "./tests/demo",
  // One worker: the rehearsal walks a single business through a single lifecycle, and two
  // of them racing would approve each other's rows.
  workers: 1,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  // No retries. A rehearsal that passes on the second attempt has not told you the demo
  // will work; it has told you it works sometimes, which is worse than a clear failure.
  retries: 0,
  reporter: "list",
  timeout: 60_000,
  use: {
    ...devices["Desktop Chrome"],
    locale: "fa-IR",
    trace: "retain-on-failure",
    ...(chromiumExecutablePath
      ? { launchOptions: { executablePath: chromiumExecutablePath } }
      : {}),
  },
});
