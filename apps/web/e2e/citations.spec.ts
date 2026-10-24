/// <reference lib="dom" />
import { expect, test, type Page } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-16 (design/specs/ux-refresh-spec.md, mockup 1): the citation panel is a column from
// 1024 px, a right drawer from 768 px and a bottom sheet on phone; markers are at least
// 24 px targets. Binding list item 3 is guarded by complianceUi.spec.ts.
const scenario = (name: string) => SCENARIOS.find((s) => s.name === name)!;
const panel = (page: Page) => page.getByRole("complementary", { name: "Citations" });
const position = (page: Page) => panel(page).evaluate((el) => getComputedStyle(el).position);

async function openFirst(page: Page) {
  await openScenario(page, scenario("08b-chat-answer"));
  await page.getByRole("button", { name: "Citation 1" }).click();
  await expect(panel(page)).toBeVisible();
}

test("desktop: a column beside the thread that scrolls on its own", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.desktop);
  await openScenario(page, scenario("09-chat-long-answer-many-citations"));
  expect(await position(page)).toBe("sticky");
  const box = (await panel(page).boundingBox())!;
  expect(box.width).toBe(380);
  const scrolls = await panel(page)
    .locator("ol")
    .evaluate((ol) => ol.scrollHeight > ol.clientHeight);
  expect(scrolls).toBe(true);
  await expect(panel(page).getByText("of 14")).toBeHidden();
  // The panel's own scrolling never makes the page taller than the thread.
  const heights = await page.evaluate(() => [
    document.documentElement.scrollHeight,
    document.querySelector("main ol")!.getBoundingClientRect().bottom + window.scrollY,
  ]);
  expect(heights[0]).toBeLessThan(heights[1] + 400);
});

test("tablet: a drawer on the right", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 900 });
  await openFirst(page);
  expect(await position(page)).toBe("fixed");
  const box = (await panel(page).boundingBox())!;
  expect(box.x + box.width).toBe(900);
  expect(box.height).toBe(900);
  await expect(panel(page).getByTestId("citation-2")).toBeVisible();
});

test("phone: a bottom sheet with one source, previous and next", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.phone);
  await openFirst(page);
  const box = (await panel(page).boundingBox())!;
  expect(box.y + box.height).toBe(VIEWPORTS.phone.height);
  expect(box.height).toBeLessThanOrEqual(VIEWPORTS.phone.height * 0.85);
  await expect(panel(page).getByRole("heading", { name: "Sources 1 of 2" })).toBeVisible();
  await expect(panel(page).getByTestId("citation-1")).toBeVisible();
  await expect(panel(page).getByTestId("citation-2")).toBeHidden();
  await expect(panel(page).getByRole("button", { name: "Previous source" })).toBeDisabled();
  await panel(page).getByRole("button", { name: "Next source" }).click();
  await expect(panel(page).getByRole("heading", { name: "Sources 2 of 2" })).toBeVisible();
  await expect(panel(page).getByTestId("citation-2")).toBeVisible();
  await expect(panel(page).getByTestId("citation-1")).toBeHidden();
  await expect(panel(page).getByRole("button", { name: "Next source" })).toBeDisabled();
});

test("Escape closes the panel", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.phone);
  await openFirst(page);
  await panel(page).getByRole("button", { name: "Close" }).focus();
  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
});

test("markers are at least 24 px targets and keep their names", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.phone);
  await openScenario(page, scenario("08b-chat-answer"));
  for (const name of ["Citation 1", "Citation 2"]) {
    const box = (await page.getByRole("button", { name }).boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(24);
    expect(box.height).toBeGreaterThanOrEqual(24);
  }
});
