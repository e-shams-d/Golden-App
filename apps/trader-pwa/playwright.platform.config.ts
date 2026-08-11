import { defineConfig, devices } from "@playwright/test";

/**
 * Platform-contract specs: what the *browser* guarantees, not what our pages render.
 *
 * Separate from `playwright.config.ts` for one reason that is not tidiness. That
 * config declares a `webServer` which builds and boots the Next standalone output, so
 * a spec placed under its `testDir` cannot run without a production build of the app.
 * These specs serve their own responses and need no application at all — folding them
 * in would make a check about cookie storage depend on a Next build succeeding.
 *
 * Desktop Chromium rather than the a11y config's Pixel 7 profile: cookie storage is
 * not device-dependent, and a mobile emulation profile would imply it might be.
 */

const chromiumExecutablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
const outputDirectory = process.env.PLAYWRIGHT_OUTPUT_DIR;

export default defineConfig({
  ...(outputDirectory ? { outputDir: outputDirectory } : {}),
  testDir: "./tests/platform",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  // No retries. A cookie-storage rule either holds or does not; a retry would only
  // convert a real regression into an intermittent one.
  retries: 0,
  reporter: process.env.CI ? "html" : "list",
  use: {
    locale: "fa-IR",
    ...(chromiumExecutablePath
      ? { launchOptions: { executablePath: chromiumExecutablePath } }
      : {}),
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"]! },
    },
  ],
});
