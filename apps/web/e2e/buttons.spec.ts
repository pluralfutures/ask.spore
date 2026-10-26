/// <reference lib="dom" />
import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-06 (design/specs/ux-refresh-spec.md): every button has an accessible name, and at
// 390 px every button is at least 44 by 44 px (WCAG 2.5.5). Two kinds are exempt until
// their own items restyle them: citation markers (UX-16) and the operator console's tabs
// (UX-09).
const MIN_TARGET_PX = 44;

function exempt(name: string, inTabs: boolean): boolean {
  return /^Citation \d+$/.test(name) || inTabs;
}

test.describe("buttons at 390 px", () => {
  test.use({ viewport: VIEWPORTS.phone, locale: "en-GB", timezoneId: "UTC" });
  for (const scenario of SCENARIOS) {
    test(scenario.name, async ({ page }) => {
      await openScenario(page, scenario);
      const buttons = await page.locator("button:visible").all();
      const small: string[] = [];
      for (const button of buttons) {
        await expect(button).toHaveAccessibleName(/\S/);
        const name = (await button.getAttribute("aria-label")) ?? (await button.innerText());
        const inTabs = await button.evaluate((el) => el.closest("nav") !== null);
        const box = await button.boundingBox();
        if (box === null || exempt(name.trim(), inTabs)) continue;
        if (box.height < MIN_TARGET_PX - 0.5 || box.width < MIN_TARGET_PX - 0.5) {
          small.push(`${name.trim()}: ${box.width.toFixed(0)}×${box.height.toFixed(0)}`);
        }
      }
      expect(small, "buttons below the 44 px touch target").toEqual([]);
    });
  }
});

test("disabled is a colour state, not opacity", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.desktop);
  await openScenario(
    page,
    SCENARIOS.find((s) => s.name === "21-ui-gallery")!,
  );
  const row = page.getByRole("row", { name: /^primary/ });
  const enabled = row.getByRole("button", { name: "Save" }).nth(1);
  const disabled = row.getByRole("button", { name: "Save" }).last();
  await expect(disabled).toBeDisabled();
  const style = (el: Element) => {
    const s = getComputedStyle(el);
    return { opacity: s.opacity, background: s.backgroundColor, color: s.color };
  };
  const on = await enabled.evaluate(style);
  const off = await disabled.evaluate(style);
  expect(off.opacity).toBe("1");
  expect(off.background).not.toBe(on.background);
  expect(off.color).not.toBe(on.color);
});
