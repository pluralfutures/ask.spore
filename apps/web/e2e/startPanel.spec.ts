/// <reference lib="dom" />
import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-14 (design/specs/ux-refresh-spec.md, mockup 2): the page's h1, the labelled question
// first, then the "Settings" card; a single model shows read-only.
const scenario = (name: string) => SCENARIOS.find((s) => s.name === name)!;

test.use({ viewport: VIEWPORTS.desktop });

test("the question comes before the settings, each labelled", async ({ page }) => {
  await openScenario(page, scenario("07b-start-panel-choices"));
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { level: 1 })).toHaveText("New conversation");
  const question = main.getByLabel("Question");
  const settings = main.getByRole("group", { name: "Settings" });
  await expect(question).toBeVisible();
  await expect(settings).toBeVisible();
  const order = await question.evaluate(
    (q, s) => !!(q.compareDocumentPosition(s!) & Node.DOCUMENT_POSITION_FOLLOWING),
    await settings.elementHandle(),
  );
  expect(order).toBe(true);
  await expect(settings.getByLabel("Workspace")).toBeVisible();
  await expect(settings.getByLabel("Model")).toBeVisible();
});

test("a single model is shown read-only", async ({ page }) => {
  await openScenario(page, scenario("07-start-panel-single"));
  await expect(page.getByTestId("model-readonly")).toHaveText(/^Model: \S/);
  await expect(page.getByRole("combobox")).toHaveCount(0);
});

for (const name of [
  "07e-start-panel-loading",
  "07f-start-panel-error",
  "07g-start-panel-no-workspace",
]) {
  test(`the page keeps its h1 and back link: ${name}`, async ({ page }) => {
    await openScenario(page, scenario(name));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("New conversation");
    await expect(page.getByRole("link", { name: "← Conversations" })).toBeVisible();
  });
}
