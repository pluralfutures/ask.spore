/// <reference lib="dom" />
import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-18 (design/specs/ux-refresh-spec.md, mockup 3): tenant admin's section sub-nav and
// cards per section; configuration values in monospace.
const admin = SCENARIOS.find((s) => s.name === "11-tenant-admin")!;
const SECTIONS = ["Users", "Workspaces", "Chat history retention", "Sign-in", "Audit log"];

for (const [width, viewport] of Object.entries(VIEWPORTS)) {
  test(`the sub-nav links each section, in page order (${width})`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openScenario(page, admin);
    const nav = page.getByRole("navigation", { name: "Administration sections" });
    await expect(nav.getByRole("link")).toHaveText(SECTIONS);
    await expect(page.getByRole("heading", { level: 2 })).toHaveText(SECTIONS);
    await expect(nav.getByRole("link", { name: "Users" })).toHaveAttribute("aria-current", "true");
    await nav.getByRole("link", { name: "Audit log" }).click();
    await expect(page).toHaveURL(/#audit$/);
    await expect(page.getByRole("heading", { name: "Audit log" })).toBeInViewport();
    await expect(nav.getByRole("link", { name: "Audit log" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });
}

test("the SSO source's settings are shown in monospace", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.desktop);
  await openScenario(page, admin);
  const summary = page.locator("#sign-in dl");
  const fonts = await summary
    .locator("dd")
    .evaluateAll((dds) => dds.map((dd) => getComputedStyle(dd).fontFamily.includes("mono")));
  expect(fonts.slice(0, 4)).toEqual([false, false, false, false]);
  expect(fonts.length).toBeGreaterThan(4);
  expect(fonts.slice(4).every(Boolean)).toBe(true);
});
