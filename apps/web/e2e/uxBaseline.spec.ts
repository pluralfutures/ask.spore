import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { BASELINE } from "./baselines/baseline";
import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-02 (design/specs/ux-refresh-spec.md): accessibility and layout baseline for every audit
// scenario. Today's known failures are listed in baselines/ux-baseline.json; a failure not
// listed there fails the test, and so does a listed one that no longer occurs, so the list
// only ever shrinks and stays accurate.

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"];

test.describe("axe at 1440 px", () => {
  test.use({ viewport: VIEWPORTS.desktop, locale: "en-GB", timezoneId: "UTC" });
  for (const scenario of SCENARIOS) {
    test(scenario.name, async ({ page }) => {
      await openScenario(page, scenario);
      const result = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
      const found = result.violations.map((v) => v.id).sort();
      const known = BASELINE.axe[scenario.name] ?? [];
      const added = found.filter((id) => !known.includes(id));
      const gone = known.filter((id) => !found.includes(id));
      const detail = result.violations
        .filter((v) => added.includes(v.id))
        .map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`);
      expect(added, `new axe violations:\n${detail.join("\n")}`).toEqual([]);
      expect(gone, "fixed: remove these from baselines/ux-baseline.json").toEqual([]);
    });
  }
});

test.describe("no horizontal overflow at 390 px", () => {
  test.use({ viewport: VIEWPORTS.phone, locale: "en-GB", timezoneId: "UTC" });
  for (const scenario of SCENARIOS) {
    test(scenario.name, async ({ page }) => {
      await openScenario(page, scenario);
      const width = (await page.evaluate("document.documentElement.scrollWidth")) as number;
      const known = scenario.name in BASELINE.overflowAt390;
      if (known) {
        expect(width, "fixed: remove from overflowAt390 in the baseline").toBeGreaterThan(390);
      } else {
        expect(width, "the page is wider than the screen").toBeLessThanOrEqual(390);
      }
    });
  }
});
