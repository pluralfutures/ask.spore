/// <reference lib="dom" />
import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-15 (design/specs/ux-refresh-spec.md, mockup 1): reading type in the answer block,
// the notes inside it, feedback in its footer, and a composer that stays in view.
const scenario = (name: string) => SCENARIOS.find((s) => s.name === name)!;

for (const [width, viewport] of Object.entries(VIEWPORTS)) {
  test(`the composer stays in view in a long conversation (${width})`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openScenario(page, scenario("09-chat-long-answer-many-citations"));
    const question = page.getByLabel("Question");
    await expect(question).toBeInViewport();
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(question).toBeInViewport();
    await expect(page.getByRole("button", { name: "Ask" })).toBeInViewport();
  });
}

test.describe("desktop", () => {
  test.use({ viewport: VIEWPORTS.desktop });

  test("the answer reads at 16/26 and keeps its notes and feedback inside", async ({ page }) => {
    await openScenario(page, scenario("09c-chat-notes-abstain-unsupported"));
    const exports = page.getByRole("article").filter({ hasText: "Synthetic exports rose by 3%" });
    await expect(exports.getByTestId("answer-note")).toBeVisible();
    await expect(exports.getByTestId("failover")).toBeVisible();
    await expect(
      exports.locator("footer").getByRole("button", { name: "Helpful", exact: true }),
    ).toBeVisible();
    const type = await exports
      .getByText("Synthetic exports rose by 3%")
      .evaluate((el) => [getComputedStyle(el).fontSize, getComputedStyle(el).lineHeight]);
    expect(type).toEqual(["16px", "26px"]);
  });

  test("the header shows the settings as badges and the expiry", async ({ page }) => {
    await openScenario(page, scenario("08b-chat-answer"));
    const header = page.getByRole("main").locator("header");
    await expect(header.getByTestId("workspace-label")).toBeVisible();
    await expect(header.getByTestId("model-name")).toBeVisible();
    await expect(header).toContainText("Expires");
  });
});
