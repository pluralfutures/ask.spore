import { expect, test } from "@playwright/test";

import { openScenario } from "../scenarios/open";
import { SCENARIOS } from "../scenarios/scenarios";

// UX-01: one full-page snapshot per audit scenario and width (the project). A change of look
// shows up here as an image diff to review; synthetic data only (CLAUDE.md).
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
