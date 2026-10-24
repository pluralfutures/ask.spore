import { expect, test, type Locator, type Page } from "@playwright/test";

import { BASELINE } from "./baselines/baseline";
import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS, type Scenario } from "./scenarios/scenarios";

// UX-02: the keyboard paths through sign-in, consent, the start panel and citations, with
// a visible focus indicator at each stop. The focus ring's minimum width comes from the
// baseline (today the browser default, 1 px); UX-05 raises it to 2 px.

test.use({ viewport: VIEWPORTS.desktop, locale: "en-GB", timezoneId: "UTC" });

function scenario(name: string): Scenario {
  const found = SCENARIOS.find((s) => s.name === name);
  if (!found) throw new Error(`no scenario ${name}`);
  return found;
}

// Tab once; the next stop must be `target`, with an outline drawn around it.
async function tabTo(page: Page, target: Locator): Promise<void> {
  await page.keyboard.press("Tab");
  await expect(target).toBeFocused();
  await expectVisibleFocus(page);
}

async function expectVisibleFocus(page: Page): Promise<void> {
  // A string, so the Node-typed e2e config needs no DOM types.
  const [style, width] = (await page.evaluate(
    "(() => { const s = getComputedStyle(document.activeElement);" +
      " return [s.outlineStyle, parseFloat(s.outlineWidth)]; })()",
  )) as [string, number];
  expect(style, "focused element has no outline").not.toBe("none");
  expect(width).toBeGreaterThanOrEqual(BASELINE.focusRingMinWidthPx);
}

// UX-10: the first stop on every page is "Skip to content"; Enter moves focus to <main>,
// past the top bar.
async function skipToContent(page: Page): Promise<void> {
  await tabTo(page, page.getByRole("link", { name: "Skip to content" }));
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
}

test("email sign-in: skip link, email, then continue", async ({ page }) => {
  await openScenario(page, scenario("02-signin-email"));
  await tabTo(page, page.getByRole("link", { name: "Skip to content" }));
  await tabTo(page, page.getByLabel("Email"));
  await tabTo(page, page.getByRole("button", { name: "Continue" }));
});

test("consent: the full notice, the box, then the accept button once ticked", async ({ page }) => {
  await openScenario(page, scenario("05-consent-first"));
  const accept = page.getByRole("button", { name: "Accept and continue" });
  // Chromium makes a scrolling box focusable by itself; Safari does not, hence the axe
  // baseline entry (scrollable-region-focusable) until the box gets its own tab stop.
  await tabTo(page, page.getByRole("region", { name: "Full notice" }));
  await tabTo(page, page.getByRole("checkbox"));
  await expect(accept).toBeDisabled();
  await page.keyboard.press("Space");
  await tabTo(page, accept);
  await expect(accept).toBeEnabled();
});

test("start panel: skip link, back link, workspace, model, reasoning, question", async ({
  page,
}) => {
  await openScenario(page, scenario("07b-start-panel-choices"));
  await skipToContent(page);
  await tabTo(page, page.getByRole("link", { name: "← Conversations" }));
  await tabTo(page, page.getByLabel("Workspace"));
  await tabTo(page, page.getByLabel("Model"));
  await tabTo(page, page.getByRole("switch", { name: "Reasoning" }));
  await tabTo(page, page.getByLabel("Question"));
});

test("citations open from a marker and close from the panel", async ({ page }) => {
  await openScenario(page, scenario("08b-chat-answer"));
  const panel = page.getByRole("complementary", { name: "Citations" });
  const close = panel.getByRole("button", { name: "Close" });
  await page.getByRole("button", { name: "Citation 1" }).focus();
  await page.keyboard.press("Enter");
  await expect(panel).toBeVisible();
  let reached = false;
  for (let i = 0; i < 20 && !reached; i++) {
    await page.keyboard.press("Tab");
    reached = await close.evaluate((el) => el === el.ownerDocument.activeElement);
  }
  expect(reached, "the panel's Close button is reachable by Tab").toBe(true);
  await expectVisibleFocus(page);
  await page.keyboard.press("Enter");
  await expect(panel).toHaveCount(0);
});
