import { expect, test, type Route } from "@playwright/test";

import { FakeApi, type FakeFile } from "./fakeApi";

// P2A-04: a reviewer pauses a source in the content console, the file leaves the tenant's
// library, and comes back on resume. The fake answers both sides from one state, as the
// API does (the file list shows ingested sources only). Synthetic rows only (CLAUDE.md).
const WORKSPACE = "aaaaaaaa-0000-4000-8000-000000000001";
const SOURCE = "33333333-3333-4333-8333-000000000001";
const FILE: FakeFile = {
  id: SOURCE,
  type: "pdf",
  title: "Synthetic Outlook 2026",
  publisher: "Synthetic Institute",
  published_on: "2026-03-01",
  canonical_url: "https://example.org/synthetic-outlook",
  ingested_on: "2026-10-19",
  downloadable: true,
};
const OTHER: FakeFile = {
  ...FILE,
  id: "33333333-3333-4333-8333-000000000002",
  title: "Synthetic Other Note",
};

test("a reviewer pauses a source, the file leaves the library, and comes back on resume", async ({
  page,
}) => {
  const files: Record<string, FakeFile[]> = { [WORKSPACE]: [FILE, OTHER] };
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
    files,
  });
  await api.install(page);

  let status = "ingested";
  let paused: { at: string; reason: string } | null = null;
  const calls: { path: string; body: unknown }[] = [];
  const detail = () => ({
    id: SOURCE,
    type: "pdf",
    title: FILE.title,
    publisher: FILE.publisher,
    published_on: FILE.published_on,
    canonical_url: FILE.canonical_url,
    licence_basis: "publisher-terms",
    tags: ["sample-reports"],
    status,
    downloadable: true,
    site_id: null,
    takedown_due_on: null,
    possible_replacement: false,
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-21T10:00:00Z",
    review_note: null,
    review_date: null,
    proposed_by: "editor@example.org",
    approved_by: "editor@example.org",
    approved_at: "2026-10-20T10:00:00Z",
    withdrawn_at: null,
    withdrawal_reason: null,
    paused_at: paused?.at ?? null,
    paused_by: paused ? "analyst@example.org" : null,
    pause_reason: paused?.reason ?? null,
    chunk_count: 3,
    error: null,
    licence_file: false,
    stored: true,
    fetched_at: null,
    supersedes: null,
    possible_replacements: [],
    takedown: null,
    documents: [],
    history: [],
    jobs: [],
  });
  // Registered after the fake, so it answers the content console's calls first.
  await page.route("**/api/v1/content/**", async (route: Route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api\/v1/, "");
    if (path === "/content/me")
      return route.fulfill({ json: { roles: ["content_reviewer"], ragflow_ui_url: null } });
    if (path === `/content/sources/${SOURCE}`) return route.fulfill({ json: detail() });
    if (path === `/content/sources/${SOURCE}/pause`) {
      const body = route.request().postDataJSON() as { reason: string };
      calls.push({ path, body });
      status = "paused";
      paused = { at: "2026-10-25T10:00:00Z", reason: body.reason };
      files[WORKSPACE] = [OTHER];
      return route.fulfill({ json: { status, documents: 1, cache_entries_purged: 0 } });
    }
    if (path === `/content/sources/${SOURCE}/resume`) {
      calls.push({ path, body: route.request().postData() });
      status = "ingested";
      paused = null;
      files[WORKSPACE] = [FILE, OTHER];
      return route.fulfill({ json: { status, documents: 1, cache_entries_purged: null } });
    }
    return route.fallback();
  });

  const library = async () => {
    await page.goto(`/w/${WORKSPACE}/files`);
    await expect(page.getByTestId(`file-${OTHER.id}`)).toBeVisible();
  };
  await library();
  await expect(page.getByTestId(`file-${SOURCE}`)).toBeVisible();

  await page.goto(`/content/sources/${SOURCE}`);
  const pause = page.getByRole("button", { name: "Pause", exact: true });
  await expect(pause).toBeDisabled(); // a reason first
  await page.getByLabel("Pause reason").fill("Synthetic rights check");
  await pause.click();
  await expect(page.getByTestId("source-status")).toHaveText("paused");
  await expect(page.getByTestId("pause-record")).toContainText("Synthetic rights check");

  await library();
  await expect(page.getByTestId(`file-${SOURCE}`)).toHaveCount(0);

  await page.goto(`/content/sources/${SOURCE}`);
  await page.getByRole("button", { name: "Resume" }).click();
  await expect(page.getByTestId("source-status")).toHaveText("ingested");

  await library();
  await expect(page.getByTestId(`file-${SOURCE}`)).toBeVisible();
  expect(calls).toEqual([
    { path: `/content/sources/${SOURCE}/pause`, body: { reason: "Synthetic rights check" } },
    { path: `/content/sources/${SOURCE}/resume`, body: null },
  ]);
});
