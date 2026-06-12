import { defineConfig } from "@playwright/test";

/**
 * Playwright configuration for NeuroNote E2E tests.
 *
 * The Docker stack (api + web + db) is expected to be already running at
 * http://localhost:3000 and http://localhost:8000 before invoking `npm run e2e`.
 * We deliberately do NOT configure `webServer` here: a competing dev server
 * would shadow the Dockerised one and silently mask environment drift. If the
 * stack is down, tests should fail fast on the first navigation.
 *
 * Browser matrix is intentionally chromium-only for now; adding Firefox/WebKit
 * costs CI minutes without immediate signal value for this stack.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: "list",
  expect: {
    // Deterministic NLP pipeline can take a few seconds to update badges.
    timeout: 10_000,
  },
  use: {
    baseURL: "http://localhost:3000",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
