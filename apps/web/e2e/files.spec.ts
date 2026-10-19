import { expect, test } from "@playwright/test";

import { FakeApi, type FakeFile } from "./fakeApi";

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
  await page.goto("/");
  await page.getByRole("link", { name: "Synthetic Team Alpha" }).click();
  await expect(page.getByRole("heading", { name: "Files in Synthetic Team Alpha" })).toBeVisible();

  const gated = page.getByTestId(`file-${FILES[1].id}`);
  await expect(gated.getByRole("button")).toHaveCount(0);
  await expect(gated.getByRole("link", { name: "View at source" })).toHaveAttribute(
    "href",
    "https://example.org/synthetic-note",
  );
  await expect(page.getByText("site.example · Synthetic Site · 7 pages")).toBeVisible();

  const saved = page.waitForEvent("download");
  await page.getByTestId(`file-${FILES[0].id}`).getByRole("button", { name: "Download" }).click();
  expect((await saved).suggestedFilename()).toBe("Synthetic-Outlook-2026.pdf");
  expect(api.downloads).toEqual([FILES[0].id]);
});
