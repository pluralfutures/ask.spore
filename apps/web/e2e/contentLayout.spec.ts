/// <reference lib="dom" />
import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-21 (design/specs/ux-refresh-spec.md): the content console's register filter bar and
// source facts.
const scenario = (name: string) => SCENARIOS.find((s) => s.name === name)!;

test.use({ viewport: VIEWPORTS.desktop });

test("the register's filters are one search bar of labelled controls", async ({ page }) => {
  await openScenario(page, scenario("15-content-register"));
  const bar = page.getByRole("search");
  for (const name of ["Status", "Tag", "Type", "Publisher"]) {
    await expect(bar.getByLabel(name)).toBeVisible();
  }
  const tops = await bar
    .locator("select, input")
    .evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().top)));
  expect(new Set(tops).size).toBe(1); // one row on desktop
});

test("the source detail shows its facts as a definition list", async ({ page }) => {
  await openScenario(page, scenario("16-content-source-detail"));
  const terms = page.locator("dl").first().locator("dt");
  await expect(terms.first()).toHaveText("Publisher");
  await expect(page.locator("dl").first().getByTestId("source-status")).toBeVisible();
});
