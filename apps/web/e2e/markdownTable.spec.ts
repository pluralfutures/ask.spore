import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import * as F from "./scenarios/fixtures";
import { ScenarioApi } from "./scenarios/scenarioApi";

// P2B-01: a GFM table in an answer is a table, scrolls inside its own region (the page never
// scrolls sideways at phone width) and keeps a citation marker in a cell working.
const ID = "11111111-0000-4000-8000-000000000990";
const WIDE =
  "| Role | What the passage says | Mechanism | Another long column heading | Yet another heading |\n" +
  "|---|---|---|---|---|\n" +
  "| Procuring hospital | Once the product specifications have been set, additional sustainable features could be identified as award criteria [1] | Tender specifications | A very long cell value that cannot wrap below its longest word: Supercalifragilisticexpialidocious_Supercalifragilisticexpialidocious | Internal stakeholder engagement |";

async function open(page: import("@playwright/test").Page) {
  const api = new ScenarioApi({
    conversationDetail: {
      [ID]: F.conversation(ID, "Synthetic table", [
        F.message("user", "Synthetic table question"),
        F.message("assistant", WIDE, { citations: F.MANY_CITATIONS }),
      ]),
    },
  });
  await api.install(page);
  await page.goto(`/c/${ID}`);
  await page.getByRole("table").waitFor();
}

test("a table renders as a table with column headers and passes axe", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  await expect(page.getByRole("columnheader")).toHaveCount(5);
  await expect(page.getByRole("group", { name: "Table" })).toBeVisible();
  const result = await new AxeBuilder({ page })
    .include("[aria-label='Table']")
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"])
    .analyze();
  expect(result.violations.map((v) => v.id)).toEqual([]);
});

test("at 390 px the table scrolls in its own region, not the page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await open(page);
  expect(await page.evaluate("document.documentElement.scrollWidth")).toBeLessThanOrEqual(390);
  const region = page.getByRole("group", { name: "Table" });
  expect(await region.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
  await region.focus();
  await expect(region).toBeFocused();
});

test("a citation marker inside a cell opens the citation panel", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  await page.getByRole("cell").getByRole("button", { name: "Citation 1" }).click();
  await expect(page.getByRole("complementary", { name: "Citations" })).toBeVisible();
});
