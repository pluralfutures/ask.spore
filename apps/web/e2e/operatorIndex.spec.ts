/// <reference lib="dom" />
import { expect, test, type Page } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-19 (design/specs/ux-refresh-spec.md): the operator console's tenants, downloadable
// files and notices are tables; the totals' numbers are right-aligned.
const scenario = (name: string) => SCENARIOS.find((s) => s.name === name)!;
const card = (page: Page, title: string) =>
  page.locator("section").filter({ has: page.getByRole("heading", { name: title, exact: true }) });

test.use({ viewport: VIEWPORTS.desktop });

test("tenants, files and notices are tables", async ({ page }) => {
  await openScenario(page, scenario("12-operator-console"));
  await expect(card(page, "Tenants").getByRole("columnheader")).toHaveText([
    "Tenant",
    "Slug",
    "Status",
    "Admins",
  ]);
  await expect(
    card(page, "Tenants").getByRole("link", { name: "Totals across tenants" }),
  ).toBeVisible();
  await expect(card(page, "Downloadable files").getByRole("columnheader")).toHaveText([
    "Downloadable",
    "Title",
    "Publisher",
    "Licence basis",
    "Tags",
  ]);
  // Each checkbox is named by its file's title.
  const boxes = card(page, "Downloadable files").getByRole("checkbox");
  expect(await boxes.count()).toBeGreaterThan(0);
  for (const box of await boxes.all()) await expect(box).toHaveAccessibleName(/\S/);
  await expect(card(page, "Notices").getByRole("columnheader")).toHaveText([
    "Date",
    "Tenant",
    "Kind",
  ]);
});

test("totals right-align their numbers", async ({ page }) => {
  await openScenario(page, scenario("14-operator-aggregates"));
  const cells = page.locator("td[data-numeric]");
  expect(await cells.count()).toBeGreaterThan(0);
  const aligns = await cells.evaluateAll((tds) => tds.map((td) => getComputedStyle(td).textAlign));
  expect(new Set(aligns)).toEqual(new Set(["right"]));
});

test.describe("phone", () => {
  test.use({ viewport: VIEWPORTS.phone });

  test("stacked rows keep a cell's parts together and labels in the body font", async ({
    page,
  }) => {
    await openScenario(page, scenario("12-operator-console"));
    const title = page.locator('td[data-label="Title"]').filter({ hasText: "(no stored copy)" });
    await expect(title.locator("> *")).toHaveCount(1);
    const admins = page.locator('td[data-label="Admins"]').first();
    await expect(admins).toHaveCSS("text-align", "left");
    const slug = page.locator('td[data-label="Slug"]').first();
    const labelFont = await slug.evaluate((td) => getComputedStyle(td, "::before").fontFamily);
    expect(labelFont).not.toContain("mono");
  });
});
