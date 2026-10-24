import { defineConfig, devices } from "@playwright/test";

// UX-01 visual-regression suite (design/specs/ux-refresh-spec.md): every audit scenario at
// 1440 and 390 px against the scenario fake. Since UX-05 the snapshots are generated in the
// pinned Playwright image (e2e/visual/run-in-image.sh), which CI also uses, so they do not
// depend on the machine. Run with `pnpm test:visual`; update with
// `pnpm test:visual --update-snapshots`.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;
const chrome = devices["Desktop Chrome"];

export default defineConfig({
  testDir: "e2e/visual",
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}-{projectName}{ext}",
  forbidOnly: !!process.env.CI,
  reporter: "list",
  expect: {
    // threshold 0.02: the default per-pixel tolerance (0.2) lets a change as small as
    // slate-100 to white pass, and the refresh's palette steps are that small.
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      threshold: 0.02,
      maxDiffPixelRatio: 0.001,
    },
  },
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "off",
    locale: "en-GB",
    timezoneId: "UTC",
    launchOptions: { executablePath },
  },
  projects: [
    {
      name: "desktop",
      use: { ...chrome, viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
    },
    {
      name: "phone",
      use: { ...chrome, viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 },
    },
  ],
  webServer: {
    command: "pnpm exec vite --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
  },
});
