import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-12 (design/specs/ux-refresh-spec.md): the consent gate's notice keeps its Markdown
// structure, its scrolling box can be reached and scrolled from the keyboard, and on phone
// the accept row stays in view. Binding list item 1 is guarded by complianceUi.spec.ts.
const first = SCENARIOS.find((s) => s.name === "05-consent-first")!;

test.describe("desktop", () => {
  test.use({ viewport: VIEWPORTS.desktop });

  test("the notice's headings and lists render as headings and lists", async ({ page }) => {
    await openScenario(page, first);
    const full = page.getByRole("region", { name: "Full notice" });
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(full.getByRole("heading", { level: 3 })).toHaveText([
      "1. What this service is",
      "2. Your data",
      "Kept for you",
      "3. Your rights",
    ]);
    await expect(full.getByRole("listitem")).toHaveText([
      "Synthetic list item on conversations.",
      "Synthetic list item on audit records.",
    ]);
    const summary = page.getByRole("region", { name: "In short" });
    await expect(summary.getByRole("listitem")).toHaveCount(3);
    const marker = await summary
      .getByRole("listitem")
      .first()
      .evaluate((li) => getComputedStyle(li).listStyleType);
    expect(marker).toBe("disc");
  });

  test("the full notice scrolls from the keyboard", async ({ page }) => {
    await openScenario(page, first);
    const full = page.getByRole("region", { name: "Full notice" });
    await expect(full).toHaveAttribute("tabindex", "0");
    await full.focus();
    const before = await full.evaluate((el) => el.scrollTop);
    await page.keyboard.press("PageDown");
    await expect.poll(() => full.evaluate((el) => el.scrollTop)).toBeGreaterThan(before);
  });
});

test.describe("phone", () => {
  test.use({ viewport: VIEWPORTS.phone });

  test("the accept row stays in view while the notice scrolls", async ({ page }) => {
    await openScenario(page, first);
    const accept = page.getByRole("button", { name: "Accept and continue" });
    const box = page.getByRole("checkbox", { name: "I have read the notice (v1) and accept it." });
    // At the top of the page and halfway down, both are on screen.
    for (const y of [0, 600]) {
      await page.evaluate((top) => window.scrollTo(0, top), y);
      await expect(accept).toBeInViewport({ ratio: 1 });
      await expect(box).toBeInViewport({ ratio: 1 });
    }
    // The page scrolls, not a box inside it.
    const inner = await page
      .getByRole("region", { name: "Full notice" })
      .evaluate((el) => el.scrollHeight > el.clientHeight);
    expect(inner).toBe(false);
  });
});
