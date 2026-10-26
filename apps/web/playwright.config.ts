import { defineConfig, devices } from "@playwright/test";

// Smoke tests against the Vite dev server with the API mocked per test (page.route).
// PLAYWRIGHT_CHROMIUM_EXECUTABLE points at a preinstalled Chromium when the bundled
// one is not installed (`pnpm exec playwright install chromium` otherwise).
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;

export default defineConfig({
  testDir: "e2e",
  // The UX-01 visual suite has its own config (playwright.visual.config.ts).
  testIgnore: "visual/**",
  // Every test mocks the API itself, so tests share no state. Parallel by test, not by file,
  // so the CI shards (`--shard`, ci.yml) get equal work.
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "off",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], launchOptions: { executablePath } } },
  ],
  webServer: {
    command: "pnpm exec vite --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
  },
});
