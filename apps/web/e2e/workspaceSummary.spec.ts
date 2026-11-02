import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import * as F from "./scenarios/fixtures";

// P2B-05: the "Sources in this workspace" card on the home page, its wording (approved by
// the owner on Oct 27, 2026) and its behaviour. Synthetic data only (CLAUDE.md).
const FULL = {
  document_count: 128,
  publisher_count: 14,
  top_publishers: ["Synthetic Publisher A", "Synthetic Publisher B", "Synthetic Publisher C"],
  first_year: 2019,
  last_year: 2026,
  last_updated: "2026-10-24",
};
const SMALL = {
  document_count: 1,
  publisher_count: 1,
  top_publishers: ["Synthetic Publisher A"],
  first_year: 2026,
  last_year: 2026,
  last_updated: "2026-10-01",
};
const EMPTY = {
  document_count: 0,
  publisher_count: 0,
  top_publishers: [],
  first_year: null,
  last_year: null,
  last_updated: null,
};
const home = (summaries: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({
  name: "home",
  url: "/",
  options: { summaries: summaries as Record<string, never>, ...extra },
});
const card = (page: import("@playwright/test").Page) => page.getByTestId("workspace-summary");

test("shows the approved wording for the selected workspace", async ({ page }) => {
  await openScenario(page, home({ [F.WS_MARKETS.id]: FULL }));
  await expect(card(page).getByRole("heading", { level: 2 })).toHaveText(
    "Sources in this workspace",
  );
  await expect(card(page).getByRole("listitem")).toHaveText([
    "128 documents from 14 publishers",
    "Including Synthetic Publisher A, Synthetic Publisher B, Synthetic Publisher C and 11 more",
    "Published 2019 to 2026",
    "Last updated 24 Oct 2026",
  ]);
  const link = card(page).getByRole("link", { name: "See all files in this workspace" });
  await expect(link).toHaveText("See all files");
  await expect(link).toHaveAttribute("href", `/w/${F.WS_MARKETS.id}/files`);
});

test("one document and one publisher read in the singular", async ({ page }) => {
  await openScenario(page, home({ [F.WS_MARKETS.id]: SMALL }));
  await expect(card(page).getByRole("listitem")).toHaveText([
    "1 document from 1 publisher",
    "From Synthetic Publisher A",
    "Published in 2026",
    "Last updated 1 Oct 2026",
  ]);
});

test("an empty workspace says so, with no figures and no link", async ({ page }) => {
  await openScenario(page, home({ [F.WS_MARKETS.id]: EMPTY }));
  await expect(card(page)).toContainText("No documents have been added to this workspace yet.");
  await expect(card(page).getByRole("link")).toHaveCount(0);
  await expect(card(page).getByRole("listitem")).toHaveCount(0);
});

test("the card follows the workspace chooser", async ({ page }) => {
  const api = await openScenario(
    page,
    home(
      { [F.WS_MARKETS.id]: FULL, [F.WS_POLICY.id]: SMALL },
      { workspaces: [F.WS_MARKETS, F.WS_POLICY] },
    ),
  );
  await expect(card(page)).toContainText("128 documents");
  await page.getByRole("combobox", { name: "Workspace" }).selectOption(F.WS_POLICY.id);
  await expect(card(page)).toContainText("1 document from 1 publisher");
  expect(api.summaryRequests).toEqual([F.WS_MARKETS.id, F.WS_POLICY.id]);
});

test("if the summary cannot be loaded the card is left out and the page still works", async ({
  page,
}) => {
  await openScenario(page, home({}));
  await expect(
    page.getByRole("heading", { name: "What would you like to research?" }),
  ).toBeVisible();
  await expect(card(page)).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("no card without a workspace", async ({ page }) => {
  const api = await openScenario(page, {
    name: "home",
    url: "/",
    options: { workspaces: [] },
  });
  await expect(card(page)).toHaveCount(0);
  expect(api.summaryRequests).toEqual([]);
});

test("the card passes axe and does not widen the page at phone width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openScenario(page, home({ [F.WS_MARKETS.id]: FULL }));
  await expect(card(page)).toBeVisible();
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"])
    .analyze();
  expect(result.violations.map((v) => v.id)).toEqual([]);
  expect(await page.evaluate("document.documentElement.scrollWidth")).toBeLessThanOrEqual(390);
});
