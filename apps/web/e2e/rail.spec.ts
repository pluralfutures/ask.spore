import { expect, test } from "@playwright/test";

import * as F from "./scenarios/fixtures";
import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS, type Scenario } from "./scenarios/scenarios";

// UX-13 (design/specs/ux-refresh-spec.md): the conversation list is the home page and,
// from 1024 px, the chat's left rail; Delete is in each row's menu, behind a dialog.
const scenario = (name: string) => SCENARIOS.find((s) => s.name === name)!;
const FIRST = F.CONVERSATION_SUMMARIES[0] as { id: string; title: string };
const inFirst: Scenario = {
  name: "first",
  url: `/c/${FIRST.id}`,
  options: { conversationDetail: { [FIRST.id]: F.conversation(FIRST.id, FIRST.title, []) } },
};
const rail = (page: import("@playwright/test").Page) =>
  page.getByRole("navigation", { name: "Conversations" });

test.describe("desktop", () => {
  test.use({ viewport: VIEWPORTS.desktop, locale: "en-GB", timezoneId: "UTC" });

  test("the chat has the rail: new, Recent, each row with its expiry, the current one marked", async ({
    page,
  }) => {
    await openScenario(page, inFirst);
    await expect(rail(page).getByRole("link", { name: "New conversation" })).toBeVisible();
    await expect(rail(page).getByText("Recent", { exact: true })).toBeVisible();
    const rows = rail(page).getByRole("listitem");
    await expect(rows).toHaveCount(5);
    for (const row of await rows.all()) await expect(row).toContainText("Expires");
    const current = rail(page).locator("[aria-current=page]");
    await expect(current).toHaveCount(1);
    await expect(current).toContainText(FIRST.title);
  });

  test("the start panel has the rail with no current row", async ({ page }) => {
    await openScenario(page, scenario("07-start-panel-single"));
    await expect(rail(page).getByRole("listitem")).toHaveCount(5);
    await expect(rail(page).locator("[aria-current=page]")).toHaveCount(0);
  });

  test("deleting the open conversation from the rail goes home", async ({ page }) => {
    await openScenario(page, inFirst);
    await rail(page)
      .getByRole("button", { name: `Actions for ${FIRST.title}` })
      .click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete this conversation permanently?" });
    await dialog.getByRole("button", { name: "Delete" }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Welcome to /);
  });

  test("the full list shows the same rows with their menus", async ({ page }) => {
    await openScenario(page, scenario("06-conversations"));
    const rows = page.getByRole("main").getByRole("listitem");
    await expect(
      rows.filter({ has: page.getByRole("button", { name: /^Actions for / }) }),
    ).toHaveCount(5);
    await expect(rows.nth(2)).toContainText("Untitled conversation");
  });

  test("/conversations lists every conversation with its expiry (HP-02)", async ({ page }) => {
    await openScenario(page, { ...scenario("06-conversations"), url: "/conversations" });
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Conversations");
    const rows = page.getByRole("main").getByRole("listitem").filter({ hasText: "Expires" });
    await expect(rows).toHaveCount(5);
    await expect(
      page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Home" }),
    ).toHaveAttribute("aria-current", "page");
  });

  test("the list's loading, empty and error states", async ({ page }) => {
    await openScenario(page, scenario("06c-conversations-empty"));
    await expect(page.getByText("No conversations yet.")).toBeVisible();
    await openScenario(page, scenario("06e-conversations-error"));
    await expect(page.getByText("Could not load conversations.")).toBeVisible();
  });
});

for (const [width, viewport] of [
  ["tablet", { width: 900, height: 900 }],
  ["phone", VIEWPORTS.phone],
] as const) {
  test(`no rail on ${width}: the back link leads to the list`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openScenario(page, inFirst);
    await expect(rail(page)).toBeHidden();
    await page.getByRole("link", { name: "← Conversations" }).click();
    await expect(page).toHaveURL(/\/conversations$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Conversations");
  });
}
