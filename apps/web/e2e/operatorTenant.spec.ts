import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-20 (design/specs/ux-refresh-spec.md): the operator tenant page's spend meter and
// threshold rows, and its forms on the form components.
const scenario = (name: string) => SCENARIOS.find((s) => s.name === name)!;

test.use({ viewport: VIEWPORTS.desktop });

test("spend shows the cap as a meter named by its line, and one row per threshold", async ({
  page,
}) => {
  await openScenario(page, scenario("13e-operator-tenant-spend"));
  const meter = page.getByRole("meter");
  await expect(meter).toHaveAccessibleName(/^External models: .* of .*\(\d+%\)$/);
  const now = Number(await meter.getAttribute("aria-valuenow"));
  expect(now).toBeGreaterThanOrEqual(0);
  expect(now).toBeLessThanOrEqual(100);
  const rows = page.getByTestId(/^threshold-/);
  expect(await rows.count()).toBeGreaterThan(0);
  for (const row of await rows.all()) {
    await expect(row).toContainText(/^\d+% at .+:\s*(reached|not reached)/);
  }
});

test("entitlements group their options under strong legends", async ({ page }) => {
  await openScenario(page, scenario("13-operator-tenant-entitlements"));
  for (const name of [
    "Answer modes",
    "Enabled models",
    "External models (served outside the EU)",
  ]) {
    await expect(page.getByRole("group", { name })).toBeVisible();
  }
  await expect(page.getByLabel("Monthly spend cap (EUR)")).toBeVisible();
});

test("the login policy is three switches and a save button", async ({ page }) => {
  await openScenario(page, scenario("13b-operator-tenant-login"));
  await expect(page.getByRole("heading", { name: "Login policy" })).toBeVisible();
  await expect(page.getByRole("switch")).toHaveCount(3);
  await expect(page.getByRole("button", { name: "Save login policy" })).toBeVisible();
});

test("an open support grant is read from its own tab, read only", async ({ page }) => {
  await openScenario(page, scenario("13-operator-tenant-entitlements"));
  await page
    .getByRole("navigation", { name: "Tenant settings" })
    .getByRole("link", { name: "Support access" })
    .click();
  const row = page.getByTestId(/^grant-/);
  await expect(row).toContainText("Settings");
  await expect(row).toContainText("our answers stopped citing");
  await row.getByRole("button", { name: "View" }).click();
  await expect(page.getByText("Chat history retention: 14 days")).toBeVisible();
  await expect(page.getByText(/^Instructions v2: Synthetic instructions/)).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
});
