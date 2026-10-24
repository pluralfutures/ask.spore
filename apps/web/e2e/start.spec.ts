import { expect, test } from "@playwright/test";

import { FakeApi, spendCapNotice, type FakeModel, type FakeWorkspace } from "./fakeApi";

// P1a-12: from the start panel to a cited answer, against the fake API.
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
    default_model: "eu-deep",
    default_reasoning: true,
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
    id: "eu-deep",
    display_name: "Synthetic EU Deep",
    external: false,
    reasoning_switch: true,
    default: false,
  },
  {
    id: "vendor/external-large",
    display_name: "Synthetic External Large",
    external: true,
    reasoning_switch: true,
    default: false,
  },
];

test("starts a conversation from the panel and gets a cited answer", async ({ page }) => {
  const api = new FakeApi({ workspaces: WORKSPACES, models: MODELS });
  await api.install(page);

  await page.goto("/");
  await page.getByRole("link", { name: "New conversation" }).click();

  const workspace = page.getByLabel("Workspace");
  const model = page.getByLabel("Model");
  const reasoning = page.getByLabel("Reasoning");
  // Pre-filled from the first workspace's defaults.
  await expect(model).toHaveValue("eu-fast");
  await expect(reasoning).not.toBeChecked();
  // Another workspace brings its own defaults.
  await workspace.selectOption({ label: "Synthetic Team Beta" });
  await expect(model).toHaveValue("eu-deep");
  await expect(reasoning).toBeChecked();
  await expect(page.getByTestId("external-note")).toHaveCount(0);

  // External models say so in plain words, in the list and once chosen.
  await expect(model.locator("option", { hasText: "served outside the EU" })).toHaveText(
    "Synthetic External Large (served outside the EU)",
  );
  await model.selectOption("vendor/external-large");
  await expect(page.getByTestId("external-note")).toHaveText(
    "This model is served outside the EU.",
  );

  await page.getByLabel("Question").fill("How did synthetic capacity change?");
  await page.getByRole("button", { name: "Start" }).click();

  await expect(page.getByText("Synthetic capacity grew by 12% in 2025")).toBeVisible();
  expect(api.created).toEqual([
    {
      workspace_id: "aaaaaaaa-0000-4000-8000-000000000002",
      model: "vendor/external-large",
      reasoning: true,
    },
  ]);
  expect(api.asked.map((a) => a.body)).toEqual([
    { question: "How did synthetic capacity change?" },
  ]);

  // The header shows the fixed choice, with nothing to change it.
  await expect(page.getByTestId("workspace-label")).toHaveText("Synthetic Team Beta");
  await expect(page.getByTestId("model-name")).toHaveText("Synthetic External Large");
  await expect(page.getByTestId("reasoning-badge")).toHaveText("Reasoning on");
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await expect(page.getByRole("switch")).toHaveCount(0);

  await page.getByRole("button", { name: "Citation 1" }).click();
  const panel = page.getByRole("complementary", { name: "Citations" });
  await expect(panel.getByTestId("citation-1")).toContainText("Synthetic Outlook 2026");

  // A follow-up question stays in the same conversation; a reload asks nothing again.
  await page.getByLabel("Question").fill("And in 2026?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByText("Synthetic capacity grew by 12% in 2025").nth(1)).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("model-name")).toHaveText("Synthetic External Large");
  expect(api.asked).toHaveLength(2);
  expect(new Set(api.asked.map((a) => a.conversation)).size).toBe(1);
});

test("shows the spend-cap fallback notice from the create route", async ({ page }) => {
  const api = new FakeApi({ workspaces: WORKSPACES, models: MODELS, spendCapFallback: "eu-fast" });
  await api.install(page);

  await page.goto("/new");
  await page.getByLabel("Model").selectOption("vendor/external-large");
  await page.getByLabel("Question").fill("How did synthetic capacity change?");
  await page.getByRole("button", { name: "Start" }).click();

  await expect(page.getByRole("status")).toHaveText(spendCapNotice("Synthetic EU Fast"));
  await expect(page.getByTestId("model-name")).toHaveText("Synthetic EU Fast");
  await expect(page.getByText("Synthetic capacity grew by 12% in 2025")).toBeVisible();
});

test("hides the choosers with one workspace and one model", async ({ page }) => {
  const api = new FakeApi({ workspaces: WORKSPACES.slice(0, 1), models: MODELS.slice(0, 1) });
  await api.install(page);

  await page.goto("/new");
  await expect(page.getByText("Workspace: Synthetic Team Alpha")).toBeVisible();
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await page.getByLabel("Reasoning").check();
  await page.getByLabel("Question").fill("How did synthetic capacity change?");
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByTestId("reasoning-badge")).toBeVisible();
  expect(api.created).toEqual([
    { workspace_id: "aaaaaaaa-0000-4000-8000-000000000001", model: "eu-fast", reasoning: true },
  ]);
});

test("keeps no history when the tenant's retention is 0 days", async ({ page }) => {
  // P1b-14: each question is a conversation of its own, deleted when its answer ends.
  const api = new FakeApi({ workspaces: WORKSPACES, models: MODELS, noHistory: true });
  await api.install(page);

  await page.goto("/new");
  await page.getByLabel("Workspace").selectOption({ label: "Synthetic Team Beta" });
  await page.getByLabel("Question").fill("How did synthetic capacity change?");
  await page.getByRole("button", { name: "Start" }).click();

  await expect(page.getByText("Synthetic capacity grew by 12% in 2025")).toBeVisible();
  await expect(page.getByTestId("no-history")).toContainText("keeps no chat history");
  await expect(page.getByText("Conversation not found.")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Helpful" })).toHaveCount(0);

  await page.getByLabel("Question").fill("And in 2026?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByText("Synthetic capacity grew by 12% in 2025").nth(1)).toBeVisible();
  await expect(page.getByText("How did synthetic capacity change?")).toBeVisible();

  // The follow-up started a new conversation with the same fixed choice.
  expect(api.created).toEqual([
    { workspace_id: "aaaaaaaa-0000-4000-8000-000000000002", model: "eu-deep", reasoning: true },
    {
      workspace_id: "aaaaaaaa-0000-4000-8000-000000000002",
      mode: "corpus_only",
      model: "eu-deep",
      reasoning: true,
    },
  ]);
  expect(new Set(api.asked.map((a) => a.conversation)).size).toBe(2);
  await page.goto("/");
  await expect(page.getByText("How did synthetic capacity change?")).toHaveCount(0);
});
