import { expect, test, type Page } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS, type Scenario } from "./scenarios/scenarios";

// UX-24 (design/specs/ux-refresh-spec.md): the automated part of the screen-reader check.
// 1. The accessibility tree of the five flows (sign-in, consent, start, chat with
//    citations, tenant admin) is recorded in screenReader.spec.ts-snapshots/: it is what a
//    screen reader reads, in reading order, so a change to it is reviewed like a
//    screenshot (`pnpm test:e2e e2e/screenReader.spec.ts --update-snapshots`).
// 2. Where focus goes, and what is announced, at each step that changes the page.

test.use({ viewport: VIEWPORTS.desktop, locale: "en-GB", timezoneId: "UTC" });

function scenario(name: string): Scenario {
  const found = SCENARIOS.find((s) => s.name === name);
  if (!found) throw new Error(`no scenario ${name}`);
  return found;
}

const TREES = [
  "02-signin-email",
  "02c-signin-email-sent",
  "03b-second-factor-setup",
  "03c-second-factor-code",
  "05b-consent-changed",
  "05c-consent-error",
  "07b-start-panel-choices",
  "07h-start-panel-refused",
  "08-chat-searching",
  "08c-chat-answer-citation-open",
  "08d-chat-error",
  "09c-chat-notes-abstain-unsupported",
  "11-tenant-admin",
  "11c-tenant-admin-remove-confirm",
];

test.describe("accessibility tree", () => {
  for (const name of TREES) {
    test(name, async ({ page }) => {
      await openScenario(page, scenario(name));
      await expect(page.locator("body")).toMatchAriaSnapshot({ name: `${name}.aria.yml` });
    });
  }

  test.describe("phone", () => {
    test.use({ viewport: VIEWPORTS.phone });
    test("08c-chat-answer-citation-open", async ({ page }) => {
      await openScenario(page, scenario("08c-chat-answer-citation-open"));
      await expect(page.locator("body")).toMatchAriaSnapshot({
        name: "08c-chat-answer-citation-open-phone.aria.yml",
      });
    });
  });
});

async function isFocused(page: Page, selector: string): Promise<boolean> {
  return page.locator(selector).evaluate((el) => el === document.activeElement);
}

test.describe("focus", () => {
  test("on the chat, skip to content passes the rail and lands on the page", async ({ page }) => {
    await openScenario(page, scenario("08b-chat-answer"));
    // The scenario leaves focus in the composer; start from the skip link.
    await page.getByRole("link", { name: "Skip to content" }).focus();
    await page.keyboard.press("Enter");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "← Conversations" })).toBeFocused();
  });

  test("a page without the rail still skips to main", async ({ page }) => {
    await openScenario(page, scenario("11-tenant-admin"));
    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();
  });

  for (const [width, viewport] of Object.entries(VIEWPORTS)) {
    test(`at ${width}, a marker opens the sources with focus on their heading, and Escape returns to the marker`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await openScenario(page, scenario("08b-chat-answer"));
      const marker = page.getByRole("button", { name: "Citation 2" });
      const panel = page.getByRole("complementary", { name: "Citations" });
      await marker.focus();
      await page.keyboard.press("Enter");
      await expect(panel.getByRole("heading", { level: 2 })).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(panel).toHaveCount(0);
      await expect(marker).toBeFocused();
    });
  }

  test("Close returns focus to the marker too", async ({ page }) => {
    await openScenario(page, scenario("08b-chat-answer"));
    const marker = page.getByRole("button", { name: "Citation 1" });
    await marker.focus();
    await page.keyboard.press("Enter");
    const panel = page.getByRole("complementary", { name: "Citations" });
    await panel.getByRole("button", { name: "Close" }).click();
    await expect(panel).toHaveCount(0);
    await expect(marker).toBeFocused();
  });

  test("the remove dialog takes focus and Cancel gives it back to the row menu", async ({
    page,
  }) => {
    await openScenario(page, scenario("11-tenant-admin"));
    const menu = page.getByRole("button", { name: "Actions for invited@example.org" });
    await menu.focus();
    await page.keyboard.press("Enter");
    await page.getByRole("menuitem", { name: "Remove" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(menu).toBeFocused();
  });

  test("after skipping, a sign-in page's first stop is its field", async ({ page }) => {
    await openScenario(page, scenario("02-signin-email"));
    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter");
    expect(await isFocused(page, "main")).toBe(true);
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Email")).toBeFocused();
  });
});

test.describe("announcements", () => {
  test("searching is a polite status, and the answer arrives in a live region", async ({
    page,
  }) => {
    await openScenario(page, scenario("08-chat-searching"));
    await expect(page.getByRole("status")).toHaveText("Searching your research package…");
    // A streamed answer is written into the same polite region (08d stops mid-answer).
    await openScenario(page, scenario("08d-chat-error"));
    await expect(
      page.locator('[aria-live="polite"]').filter({ has: page.getByRole("article") }),
    ).toContainText("Synthetic capacity grew");
  });

  test("errors are announced: start refusal, chat error, consent error", async ({ page }) => {
    await openScenario(page, scenario("07h-start-panel-refused"));
    await expect(page.getByRole("alert")).toHaveText(
      "That model is not available to your organisation.",
    );
    await openScenario(page, scenario("08d-chat-error"));
    await expect(
      page.locator('[aria-live="polite"]', { hasText: "The research library is unavailable" }),
    ).toHaveCount(1);
    await openScenario(page, scenario("05c-consent-error"));
    await expect(page.getByRole("alert")).toContainText("The notice could not be loaded.");
  });

  test("the spend-cap fallback is a status", async ({ page }) => {
    await openScenario(page, scenario("08e-chat-spend-cap-notice"));
    await expect(page.getByRole("status")).toContainText("budget for models served outside the EU");
  });
});

test.describe("names in context", () => {
  test("the conversation header is a list, one item per setting", async ({ page }) => {
    await openScenario(page, scenario("09c-chat-notes-abstain-unsupported"));
    const header = page.getByRole("list").filter({ hasText: "General knowledge" });
    await expect(header.getByRole("listitem")).toHaveText([
      "Synthetic Markets",
      "Synthetic EU Standard",
      "General knowledge",
      /^Expires /,
    ]);
  });

  test("each workspace's settings are a group named by the workspace", async ({ page }) => {
    await openScenario(page, scenario("11-tenant-admin"));
    const group = page.getByRole("group", { name: "Synthetic Markets" });
    await expect(group.getByLabel("Default mode", { exact: true })).toHaveCount(1);
    await expect(group.getByRole("button", { name: "Save defaults" })).toHaveCount(1);
  });

  test("View at source is described by its source's title", async ({ page }) => {
    await openScenario(page, scenario("08c-chat-answer-citation-open"));
    const links = page.getByRole("link", { name: "View at source" });
    await expect(links.first()).toHaveAccessibleDescription("[1] Synthetic Outlook 2026");
    await expect(links.nth(1)).toHaveAccessibleDescription(
      "[2] Synthetic Regional Capacity Review",
    );
  });
});
