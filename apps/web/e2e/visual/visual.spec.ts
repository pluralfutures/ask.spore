import { expect, test } from "@playwright/test";

import { openScenario } from "../scenarios/open";
import { SCENARIOS } from "../scenarios/scenarios";

// UX-01: one full-page snapshot per audit scenario and width (the project). A change of look
// shows up here as an image diff to review; synthetic data only (CLAUDE.md).
// The clock is fixed: the audit export's dates default to the last 90 days (P2A-07), so an
// unfixed clock would change the admin page's snapshot every day.
const FIXED_NOW = new Date("2026-10-25T10:00:00Z");

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(FIXED_NOW);
});

for (const scenario of SCENARIOS) {
  test(scenario.name, async ({ page }) => {
    await openScenario(page, scenario);
    await expect(page).toHaveScreenshot(`${scenario.name}.png`, { fullPage: true });
  });
}

// The negative case: a one-colour change is caught, so a passing run means "no change".
test("a changed background colour fails the comparison", async ({ page }, testInfo) => {
  // When updating snapshots the comparison cannot fail, and would save the altered page.
  test.skip(testInfo.config.updateSnapshots !== "missing", "not while updating snapshots");
  const scenario = SCENARIOS.find((s) => s.name === "06-conversations")!;
  await openScenario(page, scenario);
  await page.addStyleTag({ content: "main { background: #ffffff !important; }" });
  await expect(
    expect(page).toHaveScreenshot(`${scenario.name}.png`, { fullPage: true, timeout: 3_000 }),
  ).rejects.toThrow();
});
