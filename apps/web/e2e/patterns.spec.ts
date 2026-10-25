/// <reference lib="dom" />
import { expect, test, type Page } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-09 (design/specs/ux-refresh-spec.md): the dialog, row-action menu, tabs, disclosure
// and table behave as the patterns promise.
const scenario = (name: string) => SCENARIOS.find((s) => s.name === name)!;
const focusedName = (page: Page) =>
  page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    return el?.getAttribute("aria-label") ?? el?.textContent?.trim() ?? "";
  });

test.describe("at 1440 px", () => {
  test.use({ viewport: VIEWPORTS.desktop, locale: "en-GB", timezoneId: "UTC" });

  test("a dialog keeps focus inside, closes on Escape, and returns focus", async ({ page }) => {
    await openScenario(page, scenario("06-conversations"));
    // UX-13: Delete is in each conversation's row menu.
    const trigger = page.getByRole("button", { name: /^Actions for / }).nth(1);
    await trigger.click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete this conversation permanently?" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
    for (let i = 0; i < 4; i++) {
      await page.keyboard.press("Tab");
      expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("cancelling a removal sends nothing and returns focus to the menu", async ({ page }) => {
    await openScenario(page, scenario("11-tenant-admin"));
    const menu = page.getByRole("button", { name: "Actions for member@example.org" });
    await menu.click();
    await page.getByRole("menuitem", { name: "Remove" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toHaveAccessibleName(
      "Remove member@example.org and delete their conversations?",
    );
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await expect(menu).toBeFocused();
  });

  test("the row menu works from the keyboard", async ({ page }) => {
    await openScenario(page, scenario("11-tenant-admin"));
    const trigger = page.getByRole("button", { name: "Actions for invited@example.org" });
    await trigger.focus();
    await page.keyboard.press("Enter");
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("menuitem", { name: "Deactivate" })).toBeFocused();
    await page.keyboard.press("ArrowDown");
    expect(await focusedName(page)).toBe("Resend invitation");
    await page.keyboard.press("End");
    expect(await focusedName(page)).toBe("Remove");
    await page.keyboard.press("ArrowDown");
    expect(await focusedName(page)).toBe("Deactivate");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test("tabs are links that mark the current section", async ({ page }) => {
    await openScenario(page, scenario("13-operator-tenant-entitlements"));
    const tabs = page.getByRole("navigation", { name: "Tenant settings" });
    await expect(tabs.getByRole("link", { name: "Entitlements" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await tabs.getByRole("link", { name: "Spend" }).click();
    await expect(page).toHaveURL(/\?tab=spend$/);
    await expect(tabs.getByRole("link", { name: "Spend" })).toHaveAttribute("aria-current", "page");
    await expect(tabs.getByRole("link", { name: "Entitlements" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  test("version history opens from the keyboard", async ({ page }) => {
    await openScenario(page, scenario("11-tenant-admin"));
    const summary = page.getByText("Version history (2)");
    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("version-2")).toBeVisible();
  });

  test("tables keep their header row; the action column is named", async ({ page }) => {
    await openScenario(page, scenario("11-tenant-admin"));
    await expect(page.getByRole("columnheader", { name: "Email" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Actions" })).toHaveCount(1);
  });
});

test.describe("at 390 px", () => {
  test.use({ viewport: VIEWPORTS.phone, locale: "en-GB", timezoneId: "UTC" });

  test("a wide table stacks into label and value pairs", async ({ page }) => {
    await openScenario(page, scenario("11-tenant-admin"));
    const cell = page.getByTestId("user-member@example.org").locator("td").nth(1);
    expect(await cell.evaluate((td) => getComputedStyle(td).display)).toBe("grid");
    expect(await cell.evaluate((td) => getComputedStyle(td, "::before").content)).toBe('"Email"');
    const box = page.locator("table").first().locator("..");
    expect(await box.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  });
});
