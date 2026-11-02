import { expect, test } from "@playwright/test";

import { FakeApi, type FakeFile } from "./fakeApi";
import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// P1a-14: the workspace file list and a download, against the fake API.
const WORKSPACE = "aaaaaaaa-0000-4000-8000-000000000001";
const FILES: FakeFile[] = [
  {
    id: "33333333-3333-4333-8333-000000000001",
    type: "pdf",
    title: "Synthetic Outlook 2026",
    publisher: "Synthetic Institute",
    published_on: "2026-03-01",
    canonical_url: "https://example.org/synthetic-outlook",
    ingested_on: "2026-10-19",
    downloadable: true,
  },
  {
    id: "33333333-3333-4333-8333-000000000002",
    type: "docx",
    title: "Synthetic Third-Party Note",
    publisher: "Synthetic Publisher",
    published_on: null,
    canonical_url: "https://example.org/synthetic-note",
    ingested_on: "2026-10-19",
    downloadable: false,
  },
];

test("lists the workspace files and downloads one", async ({ page }) => {
  const api = new FakeApi({
    workspaces: [
      {
        id: WORKSPACE,
        slug: "team-alpha",
        name: "Synthetic Team Alpha",
        default_mode: "corpus_only",
        default_model: "eu-fast",
        default_reasoning: false,
      },
    ],
    models: [],
    files: { [WORKSPACE]: FILES },
  });
  await api.install(page);
  await page.goto("/conversations");
  await page.getByRole("link", { name: "Synthetic Team Alpha" }).click();
  await expect(page.getByRole("heading", { name: "Files in Synthetic Team Alpha" })).toBeVisible();

  const gated = page.getByTestId(`file-${FILES[1].id}`);
  await expect(gated.getByRole("button")).toHaveCount(0);
  await expect(gated.getByRole("link", { name: "View at source" })).toHaveAttribute(
    "href",
    "https://example.org/synthetic-note",
  );
  // UX-17: websites are a second table.
  const site = page.getByTestId("site-site.example");
  await expect(site.getByRole("cell")).toHaveText([
    "site.example",
    "Synthetic Site",
    "7 pages",
    /^\d{1,2} \w{3} \d{4}$/,
  ]);

  const saved = page.waitForEvent("download");
  await page.getByTestId(`file-${FILES[0].id}`).getByRole("button", { name: "Download" }).click();
  expect((await saved).suggestedFilename()).toBe("Synthetic-Outlook-2026.pdf");
  expect(api.downloads).toEqual([FILES[0].id]);
});

// UX-17: the page's empty and loading states, and both tables stacked on phone.
test.describe("UX-17 states", () => {
  const named = (name: string) => SCENARIOS.find((s) => s.name === name)!;

  test("an empty workspace says so", async ({ page }) => {
    await openScenario(page, named("10b-files-empty"));
    await expect(page.getByText("No files in this workspace.")).toBeVisible();
  });

  test("the back link leads to the full list (HP-02)", async ({ page }) => {
    await openScenario(page, named("10-files"));
    await page.getByRole("link", { name: "← Conversations" }).click();
    await expect(page).toHaveURL(/\/conversations$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Conversations");
  });

  test("loading shows a skeleton", async ({ page }) => {
    await openScenario(page, named("10c-files-loading"));
    await expect(page.getByRole("status")).toHaveText("Loading…");
  });

  test("on phone both tables show label and value rows", async ({ page }) => {
    await page.setViewportSize(VIEWPORTS.phone);
    await openScenario(page, named("10-files"));
    for (const table of await page.getByRole("table").all()) {
      await expect(table.locator("thead")).toHaveCSS("position", "absolute");
      await expect(table.locator("tbody tr").first()).toHaveCSS("display", "block");
    }
  });
});

// P2B-06: an uploaded Markdown or text file is listed with its type and downloads like the
// other files.
test("lists a Markdown and a text file with their types and a download each", async ({ page }) => {
  const extra: FakeFile[] = [
    {
      ...FILES[0],
      id: "33333333-3333-4333-8333-000000000003",
      type: "markdown",
      title: "Synthetic Notes",
    },
    {
      ...FILES[0],
      id: "33333333-3333-4333-8333-000000000004",
      type: "text",
      title: "Synthetic Text",
    },
  ];
  const api = new FakeApi({
    workspaces: [
      {
        id: WORKSPACE,
        slug: "team-alpha",
        name: "Synthetic Team Alpha",
        default_mode: "corpus_only",
        default_model: "eu-fast",
        default_reasoning: false,
      },
    ],
    models: [],
    files: { [WORKSPACE]: extra },
  });
  await api.install(page);
  await page.goto(`/w/${WORKSPACE}/files`);
  for (const [file, label] of [
    [extra[0], "Markdown"],
    [extra[1], "Text"],
  ] as const) {
    const row = page.getByTestId(`file-${file.id}`);
    await expect(row).toContainText(`(${label})`);
    await expect(row.getByRole("button")).toHaveCount(1);
  }
  await page.getByTestId(`file-${extra[1].id}`).getByRole("button").click();
  await expect.poll(() => api.downloads).toEqual([extra[1].id]);
});
