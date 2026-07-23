import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Playwright specifications live under tests/a11y and must only be run by
    // Playwright, never collected by Vitest's broad default spec glob.
    include: ["test/**/*.test.ts", "test/**/*.test.tsx"],
  },
});
