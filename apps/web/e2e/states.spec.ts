import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-23 (design/specs/ux-refresh-spec.md): the access-denied pages are empty states whose
// h1 is their existing sentence; loading pages show skeletons, never a bare "Loading…".
const scenario = (name: string) => SCENARIOS.find((s) => s.name === name)!;

test.use({ viewport: VIEWPORTS.desktop });

for (const [name, sentence] of [
  ["11d-tenant-admin-not-admin", "Tenant admins only."],
  ["12b-operator-only", "Operators only."],
  ["15c-content-roles-only", "Content roles only."],
] as const) {
  test(`access denied is the page's h1: ${name}`, async ({ page }) => {
    await openScenario(page, scenario(name));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(sentence);
  });
}

for (const name of ["04-app-loading", "07e-start-panel-loading", "10c-files-loading"]) {
  test(`loading shows a skeleton: ${name}`, async ({ page }) => {
    await openScenario(page, scenario(name));
    const status = page.getByRole("status");
    await expect(status).toHaveText("Loading…");
    // The skeleton's rows, not a spinner line.
    await expect(status.locator("[aria-hidden=true]").first()).toBeVisible();
    await expect(status.locator("svg")).toHaveCount(0);
  });
}
