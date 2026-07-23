import { defineConfig, devices } from "@playwright/test";

const externalServer = process.env.PLAYWRIGHT_EXTERNAL_SERVER === "1";
const outputDirectory = process.env.PLAYWRIGHT_OUTPUT_DIR;
const chromiumExecutablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;

export default defineConfig({
  ...(outputDirectory ? { outputDir: outputDirectory } : {}),
  testDir: "./tests/a11y",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "html" : "list",
  use: {
    baseURL: "http://127.0.0.1:3100",
    locale: "fa-IR",
    trace: "on-first-retry",
    ...(chromiumExecutablePath
      ? { launchOptions: { executablePath: chromiumExecutablePath } }
      : {}),
  },
  projects: [
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"]! },
    },
  ],
  ...(externalServer
    ? {}
    : {
        webServer: {
          command:
            "node ../../packages/config/scripts/start-next-standalone.mjs trader-pwa 3100",
          url: "http://127.0.0.1:3100",
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      }),
});
