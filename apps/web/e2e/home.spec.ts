import { expect, test, type Page } from "@playwright/test";

import { FakeApi, spendCapNotice, type FakeModel, type FakeWorkspace } from "./fakeApi";
import { openScenario } from "./scenarios/open";
import * as F from "./scenarios/fixtures";

// HP-04 (design/specs/home-page-spec.md): the welcome card, the question box and the
// recent conversations on /, against the fake APIs. Synthetic data only (CLAUDE.md).
const WORKSPACES: FakeWorkspace[] = [
  {
    id: "aaaaaaaa-0000-4000-8000-000000000001",
    slug: "team-alpha",
    name: "Synthetic Team Alpha",
    default_mode: "corpus_only",
    default_model: "eu-fast",
    default_reasoning: false,
  },
  {
    id: "aaaaaaaa-0000-4000-8000-000000000002",
    slug: "team-beta",
    name: "Synthetic Team Beta",
    default_mode: "corpus_only",
    default_model: "eu-fast",
    default_reasoning: false,
  },
];
const MODELS: FakeModel[] = [
  {
    id: "eu-fast",
    display_name: "Synthetic EU Fast",
    external: false,
    reasoning_switch: true,
    default: true,
  },
  {
    id: "vendor/external-large",
    display_name: "Synthetic External Large",
    external: true,
    reasoning_switch: true,
    default: false,
  },
];

const home = (options = {}) => ({ name: "home", url: "/", options });
const welcome = (page: Page) => page.getByRole("heading", { name: /^Welcome to / });
const askHeading = (page: Page) =>
  page.getByRole("heading", { name: "What would you like to research?" });
const hide = (page: Page) => page.getByRole("button", { name: "Hide the welcome" });

test("shows the notice, the top bar, the welcome, the question and the recent list in order", async ({
  page,
}) => {
  await openScenario(page, home({ workspaces: [F.WS_MARKETS, F.WS_POLICY] }));
  await expect(page.locator("#root > [role=banner] > :first-child")).toHaveRole("note");
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link")).toHaveText([
    "Home",
  ]);
  const headings = await page
    .getByRole("main")
    .locator("h1, h2")
    .evaluateAll((els) => els.map((el) => `${el.tagName} ${el.textContent}`));
  expect(headings).toEqual([
    "H1 Welcome to Mycelium SporeBot",
    "H2 What would you like to research?",
    "H2 Recent conversations",
  ]);
  await expect(page.getByText("Pick a workspace")).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask" })).toBeVisible();
});

test("hiding the welcome moves focus to the question and lasts across a reload", async ({
  page,
}) => {
  await openScenario(page, home());
  await expect(page.getByText("Pick a workspace")).toHaveCount(0); // one workspace
  await hide(page).click();
  await expect(welcome(page)).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "What would you like to research?",
  );
  await expect(askHeading(page)).toBeFocused();
  const stored = await page.evaluate(() => Object.entries(window.localStorage));
  expect(stored).toEqual([["sporebot.welcome-hidden", "1"]]);
  await page.reload();
  await expect(askHeading(page)).toBeVisible();
  await expect(welcome(page)).toHaveCount(0);
});

test("with storage blocked the welcome still shows and Hide still works", async ({ page }) => {
  await page.addInitScript(() => {
    // Only localStorage: the Phase 0 sign-in keeps its token in sessionStorage.
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new Error("blocked");
      },
    });
  });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await openScenario(page, home());
  await expect(welcome(page)).toBeVisible();
  await hide(page).click();
  await expect(welcome(page)).toHaveCount(0);
  await expect(askHeading(page)).toBeFocused();
  expect(errors).toEqual([]);
});

test("the consent gate replaces the welcome and the question", async ({ page }) => {
  await openScenario(page, home({ consentPending: true }));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Use and privacy notice");
  await expect(welcome(page)).toHaveCount(0);
  await expect(askHeading(page)).toHaveCount(0);
});

test("shows the three latest conversations, each with its expiry, and links to all", async ({
  page,
}) => {
  await openScenario(page, home());
  expect(F.CONVERSATION_SUMMARIES).toHaveLength(5);
  const recent = page.getByRole("region", { name: "Recent conversations" });
  const rows = recent.getByRole("listitem");
  await expect(rows).toHaveCount(3);
  for (const row of await rows.all()) await expect(row).toContainText("Expires");
  await recent.getByRole("link", { name: "All conversations" }).click();
  await expect(page).toHaveURL(/\/conversations$/);
  await expect(
    page.getByRole("main").getByRole("listitem").filter({ hasText: "Expires" }),
  ).toHaveCount(5);
});

test("with no conversations the list says so and offers no link to all", async ({ page }) => {
  await openScenario(page, home({ conversations: [] }));
  await expect(page.getByText("No conversations yet.")).toBeVisible();
  await expect(page.getByRole("link", { name: "All conversations" })).toHaveCount(0);
});

test("with no workspace the question box says so", async ({ page }) => {
  await openScenario(page, home({ workspaces: [] }));
  await expect(
    page.getByText("No workspace has been set up for your organisation yet."),
  ).toBeVisible();
  await expect(page.getByLabel("Question")).toHaveCount(0);
});

test("asks from the home page with the user's own choice and gets a cited answer", async ({
  page,
}) => {
  const api = new FakeApi({ workspaces: WORKSPACES, models: MODELS });
  await api.install(page);
  await page.goto("/");
  await page.getByLabel("Workspace").selectOption({ label: "Synthetic Team Beta" });
  await page.getByLabel("Model").selectOption("vendor/external-large");
  // The external-model disclosure keeps its text on the home page (binding list item 2).
  await expect(page.getByTestId("external-note")).toHaveText(
    "This model is served outside the EU.",
  );
  await page.getByLabel("Question").fill("How did synthetic capacity change?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page).toHaveURL(/\/c\//);
  await expect(page.getByText("Synthetic capacity grew by 12% in 2025")).toBeVisible();
  // Only the user's own choice; no dataset or document IDs (CLAUDE.md).
  expect(api.created).toEqual([
    {
      workspace_id: "aaaaaaaa-0000-4000-8000-000000000002",
      model: "vendor/external-large",
      reasoning: false,
    },
  ]);
});

test("shows the spend-cap fallback notice when asked from the home page", async ({ page }) => {
  const api = new FakeApi({ workspaces: WORKSPACES, models: MODELS, spendCapFallback: "eu-fast" });
  await api.install(page);
  await page.goto("/");
  await page.getByLabel("Model").selectOption("vendor/external-large");
  await page.getByLabel("Question").fill("How did synthetic capacity change?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: spendCapNotice("Synthetic EU Fast") }),
  ).toBeVisible();
  await expect(page.getByTestId("model-name")).toHaveText("Synthetic EU Fast");
});

test("keeps no history when asked from the home page with a retention of 0", async ({ page }) => {
  const api = new FakeApi({ workspaces: WORKSPACES, models: MODELS, noHistory: true });
  await api.install(page);
  await page.goto("/");
  await page.getByLabel("Question").fill("How did synthetic capacity change?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByText("Synthetic capacity grew by 12% in 2025")).toBeVisible();
  await expect(page.getByTestId("no-history")).toContainText("keeps no chat history");
  await expect(page.getByRole("button", { name: "Helpful" })).toHaveCount(0);
});

test("no text on the home page names a retention longer than 30 days", async ({ page }) => {
  await openScenario(page, home({ workspaces: [F.WS_MARKETS, F.WS_POLICY] }));
  const text = await page.locator("body").innerText();
  for (const [, days] of text.matchAll(/(\d+)\s*days/g))
    expect(Number(days)).toBeLessThanOrEqual(30);
});
