/// <reference lib="dom" />
import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-07 (design/specs/ux-refresh-spec.md): one form-control pattern. In every scenario,
// every control has an accessible name, text inputs and selects are one height (36 px),
// every aria-describedby points at text on the page, and at 390 px each checkbox, radio
// and switch sits in a label at least 44 px tall.
const CONTROL_HEIGHT_PX = 36;
const MIN_TARGET_PX = 44;
const TEXT_CONTROLS =
  "input:visible:not([type=checkbox]):not([type=radio]):not([type=file]), select:visible";

test.describe("form controls at 1440 px", () => {
  test.use({ viewport: VIEWPORTS.desktop, locale: "en-GB", timezoneId: "UTC" });
  for (const scenario of SCENARIOS) {
    test(scenario.name, async ({ page }) => {
      await openScenario(page, scenario);
      for (const control of await page
        .locator("input:visible, select:visible, textarea:visible")
        .all()) {
        await expect(control).toHaveAccessibleName(/\S/);
      }
      const heights = await page
        .locator(TEXT_CONTROLS)
        .evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().height)));
      expect(heights.filter((h) => h !== CONTROL_HEIGHT_PX)).toEqual([]);
      const dangling = await page.locator("[aria-describedby]").evaluateAll((els) =>
        els.flatMap((el) =>
          el
            .getAttribute("aria-describedby")!
            .split(/\s+/)
            .filter((id) => !document.getElementById(id)?.textContent?.trim()),
        ),
      );
      expect(dangling, "aria-describedby without text").toEqual([]);
    });
  }
});

test.describe("checkbox, radio and switch at 390 px", () => {
  test.use({ viewport: VIEWPORTS.phone, locale: "en-GB", timezoneId: "UTC" });
  for (const scenario of SCENARIOS) {
    test(scenario.name, async ({ page }) => {
      await openScenario(page, scenario);
      const small = await page
        .locator("input[type=checkbox]:visible, input[type=radio]:visible")
        .evaluateAll(
          (els, min) =>
            els
              .map((el) => el.closest("label") ?? el)
              .filter((el) => el.getBoundingClientRect().height < min - 0.5)
              .map((el) => (el.textContent ?? "").trim() || el.outerHTML.slice(0, 80)),
          MIN_TARGET_PX,
        );
      expect(small, "below the 44 px touch target").toEqual([]);
    });
  }
});

test("a field's error is announced with it (retention)", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.desktop);
  await openScenario(
    page,
    SCENARIOS.find((s) => s.name === "11-tenant-admin")!,
  );
  const days = page.getByLabel("Days");
  await days.fill("31");
  await page.getByRole("button", { name: "Save retention" }).click();
  await expect(days).toHaveAttribute("aria-invalid", "true");
  await expect(days).toHaveAccessibleDescription(/\S/);
});
