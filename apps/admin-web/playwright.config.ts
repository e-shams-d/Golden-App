import { a11yLaunchOptions } from "@gold/config/playwright-a11y-launch";
import { defineConfig, devices } from "@playwright/test";

const externalServer = process.env.PLAYWRIGHT_EXTERNAL_SERVER === "1";
const outputDirectory = process.env.PLAYWRIGHT_OUTPUT_DIR;

export default defineConfig({
  ...(outputDirectory ? { outputDir: outputDirectory } : {}),
  testDir: "./tests/a11y",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "html" : "list",
  use: {
    baseURL: "http://127.0.0.1:3200",
    locale: "fa-IR",
    trace: "on-first-retry",
    // Both the executable override and the one canvas flag live in @gold/config, next to the
    // measurement that produced the flag.
    launchOptions: a11yLaunchOptions(),
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"]! },
    },
  ],
  ...(externalServer
    ? {}
    : {
        webServer: {
          command:
            "node ../../packages/config/scripts/start-next-standalone.mjs admin-web 3200",
          url: "http://127.0.0.1:3200",
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      }),
});
