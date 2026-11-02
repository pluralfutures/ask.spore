import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { openScenario } from "./scenarios/open";

// P2B-03: rename a conversation from the list and from the chat header, and search the list
// by title. The search runs in the browser: nothing is sent while typing and the query is
// in no URL or storage (owner decision 2). Synthetic data only (CLAUDE.md).
const list = { name: "conversations", url: "/conversations", options: {} };
const NOTES = "11111111-0000-4000-8000-000000000902";
const FERTILISER = "What drove synthetic fertiliser prices in 2025?";
const COCOA = "Synthetic cocoa supply outlook";

const search = (page: Page) =>
  page.getByRole("searchbox", { name: "Search conversations by title" });
const rows = (page: Page) => page.getByRole("listitem").filter({ hasText: "Expires" });

test("search keeps the rows whose title contains the query, ignoring case", async ({ page }) => {
  await openScenario(page, list);
  await expect(rows(page)).toHaveCount(5);
  await search(page).fill("COCOA");
  await expect(rows(page)).toHaveCount(1);
  await expect(page.getByRole("link", { name: new RegExp(COCOA) })).toBeVisible();
  // An untitled conversation is found by the words shown for it.
  await search(page).fill("untitled");
  await expect(rows(page)).toHaveCount(1);
});

test("search with no match says so and Clear search brings the list back", async ({ page }) => {
  await openScenario(page, list);
  await search(page).fill("zzz-no-such-title");
  await expect(page.getByText("No conversations match.")).toBeVisible();
  await page.getByRole("button", { name: "Clear search" }).click();
  await expect(search(page)).toHaveValue("");
  await expect(rows(page)).toHaveCount(5);
});

test("typing a search sends nothing and leaves no trace in the URL or storage", async ({
  page,
}) => {
  await openScenario(page, list);
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await search(page).pressSequentially("fertiliser", { delay: 20 });
  await expect(rows(page)).toHaveCount(1);
  expect(requests.filter((url) => url.includes("/api/"))).toEqual([]);
  expect(page.url()).not.toContain("fertiliser");
  const stored = (await page.evaluate(
    "JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])",
  )) as string;
  expect(stored).not.toContain("fertiliser");
});

test("the list page with the search box passes axe", async ({ page }) => {
  await openScenario(page, list);
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"])
    .analyze();
  expect(result.violations.map((v) => v.id)).toEqual([]);
});

test("a conversation is renamed from its row menu with Enter", async ({ page }) => {
  const api = await openScenario(page, list);
  await page.getByRole("button", { name: `Actions for ${COCOA}` }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  const field = page.getByRole("textbox", { name: "Conversation title" });
  await expect(field).toBeFocused();
  await field.fill("  Cocoa supply, revised  ");
  await field.press("Enter");
  await expect(page.getByRole("link", { name: /Cocoa supply, revised/ })).toBeVisible();
  await expect(page.getByRole("link", { name: new RegExp(COCOA) })).toHaveCount(0);
  await expect(page.locator("[aria-live=polite]").filter({ hasText: "Renamed to" })).toHaveText(
    "Renamed to Cocoa supply, revised.",
  );
  expect(api.renamed).toEqual([
    { id: "11111111-0000-4000-8000-000000000004", title: "Cocoa supply, revised" },
  ]);
  // Renamed titles are searched.
  await search(page).fill("revised");
  await expect(rows(page)).toHaveCount(1);
});

test("Escape and Cancel leave the title as it was and send nothing", async ({ page }) => {
  const api = await openScenario(page, list);
  await page.getByRole("button", { name: `Actions for ${COCOA}` }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  const field = page.getByRole("textbox", { name: "Conversation title" });
  await field.fill("Discarded");
  await field.press("Escape");
  await expect(field).toHaveCount(0);
  await expect(page.getByRole("link", { name: new RegExp(COCOA) })).toBeVisible();
  await page.getByRole("button", { name: `Actions for ${COCOA}` }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  await page.getByRole("textbox", { name: "Conversation title" }).fill("Discarded");
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("link", { name: new RegExp(COCOA) })).toBeVisible();
  expect(api.renamed).toEqual([]);
});

test("an empty or unchanged title is not sent", async ({ page }) => {
  const api = await openScenario(page, list);
  await page.getByRole("button", { name: `Actions for ${COCOA}` }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  const field = page.getByRole("textbox", { name: "Conversation title" });
  await field.fill("   ");
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  await field.fill(COCOA);
  await field.press("Enter");
  await expect(field).toHaveCount(0);
  expect(api.renamed).toEqual([]);
});

test("a failed save keeps the editor open and says so", async ({ page }) => {
  await openScenario(page, { ...list, options: { renameFails: true } });
  await page.getByRole("button", { name: `Actions for ${COCOA}` }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  await page.getByRole("textbox", { name: "Conversation title" }).fill("New title");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert")).toHaveText("The title could not be saved. Try again.");
  await expect(page.getByRole("textbox", { name: "Conversation title" })).toHaveValue("New title");
});

test("the open conversation is renamed from its header", async ({ page }) => {
  const api = await openScenario(page, { name: "chat", url: `/c/${NOTES}`, options: {} });
  const heading = page.getByRole("heading", { level: 1 });
  await expect(heading).toHaveText("Synthetic cocoa in the synthetic west");
  await page.getByRole("button", { name: "Rename this conversation" }).click();
  const field = page.getByRole("textbox", { name: "Conversation title" });
  await field.fill("Cocoa in the west");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(heading).toHaveText("Cocoa in the west");
  await expect(page.getByRole("button", { name: "Rename this conversation" })).toBeFocused();
  expect(api.renamed.map((r) => r.title)).toEqual(["Cocoa in the west"]);
});

test("rename works at phone width without sideways scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openScenario(page, list);
  await page.getByRole("button", { name: `Actions for ${FERTILISER}` }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  await expect(page.getByRole("textbox", { name: "Conversation title" })).toBeVisible();
  expect(await page.evaluate("document.documentElement.scrollWidth")).toBeLessThanOrEqual(390);
});
