import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, test, type Route } from "@playwright/test";

import { FakeApi } from "./fakeApi";

// P2SR01-05: an editor uploads a crawl from the content console, a reviewer releases it,
// the pages are listed on the site, and the site appears in the tenant's library roll-up.
// The fake answers the console and the library from one state, as the API does.
// Synthetic content only: the fixture ZIP of packages/eval/fixtures/uploads/.
const ZIP = readFileSync(
  fileURLToPath(
    new URL("../../../packages/eval/fixtures/uploads/markdown-new.zip", import.meta.url),
  ),
);
const WORKSPACE = "aaaaaaaa-0000-4000-8000-000000000001";
const SITE = "55555555-5555-4555-8555-000000000001";
const UPLOAD = "66666666-6666-4666-8666-000000000001";
const HOST = "www.example.org";
const PAGES = ["/Products/Gravies", "/Products/Broth", "/Recipes/Soup"];
const MEMBERS = [
  ["site/", "skipped_not_markdown"],
  ["site/Products/Gravies.md", "accepted"],
  ["site/Products/Broth.md", "accepted"],
  ["site/Recipes/Soup.markdown", "accepted"],
  ["site/logo.png", "skipped_not_markdown"],
] as const;

test("an editor uploads a crawl, a reviewer releases it, and tenants see the site", async ({
  page,
}) => {
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
    files: { [WORKSPACE]: [] },
  });
  await api.install(page);

  let state: "none" | "staged" | "imported" = "none";
  const calls: { path: string; fields?: string[]; body?: unknown }[] = [];
  const report = () => ({
    upload_id: UPLOAD,
    site_id: SITE,
    status: "staged",
    mode: "partial",
    crawled_on: "2026-10-30",
    accepted: 3,
    refused: 0,
    skipped: 2,
    would_withdraw: null,
    members: MEMBERS.map(([name, outcome], index) => {
      const path = PAGES.find((p) => name.includes(p.split("/").pop()!));
      return {
        index,
        name,
        outcome,
        url: outcome === "accepted" && path ? `https://${HOST}${path}` : null,
        title: outcome === "accepted" ? `Synthetic Pantry - ${index}` : null,
        published_on: null,
        note: null,
        special_category: null,
      };
    }),
  });
  const site = () => ({
    id: SITE,
    name: "Synthetic Pantry",
    start_url: `https://${HOST}/`,
    host: HOST,
    publisher: "Synthetic Pantry Co",
    licence_basis: "publisher-terms",
    tags: ["sample-web"],
    status: state === "imported" ? "approved" : "proposed",
    schedule: "none",
    max_pages: 50,
    allow_decision: state === "imported" ? "declared" : "unchecked",
    allow_checked_at: null,
    last_crawl_at: state === "imported" ? "2026-10-31T10:05:00Z" : null,
    last_crawl_status: state === "imported" ? "imported" : null,
    next_crawl_at: null,
    page_count: state === "imported" ? 3 : 0,
    blocked_count: 0,
    origin: "upload",
    last_crawled_on: state === "imported" ? "2026-10-30" : null,
  });
  const detail = () => ({
    ...site(),
    allow_patterns: [],
    deny_patterns: [],
    special_category_allow: [],
    review_note: null,
    proposed_by: "editor@example.org",
    approved_by: state === "imported" ? "editor@example.org" : null,
    approved_at: state === "imported" ? "2026-10-31T10:00:00Z" : null,
    withdrawn_at: null,
    withdrawal_reason: null,
    jobs: [],
    pages:
      state === "imported"
        ? PAGES.map((path, n) => ({
            url: `https://${HOST}${path}`,
            state: "live",
            reason: null,
            special_category: null,
            source_id: `77777777-7777-4777-8777-00000000000${n}`,
            published_on: null,
            fetched_at: "2026-10-30T00:00:00Z",
          }))
        : [],
    uploads: [
      {
        id: UPLOAD,
        status: state === "imported" ? "imported" : "staged",
        mode: "partial",
        crawled_on: "2026-10-30",
        uploaded_at: "2026-10-31T09:00:00Z",
        uploaded_by: "editor@example.org",
        released_by: state === "imported" ? "editor@example.org" : null,
        released_at: state === "imported" ? "2026-10-31T10:00:00Z" : null,
        review_note: null,
        error: null,
        member_count: 5,
        accepted_count: 3,
        refused_count: 0,
        skipped_count: 2,
        new_count: state === "imported" ? 3 : 0,
        changed_count: 0,
        unchanged_count: 0,
        blocked_count: 0,
        withdrawn_count: 0,
      },
    ],
  });
  // Registered after the fake, so these answer first.
  await page.route("**/api/v1/content/**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");
    if (path === "/content/me")
      return route.fulfill({
        json: { roles: ["content_editor", "content_reviewer"], ragflow_ui_url: null },
      });
    if (path === "/content/tags")
      return route.fulfill({
        json: [
          {
            tag: "sample-web",
            chunk_method: "naive",
            chunk_method_by_type: {},
            dataset_id: null,
            ragflow_url: null,
            sources: 0,
          },
        ],
      });
    if (path === "/content/sites") return route.fulfill({ json: state === "none" ? [] : [site()] });
    if (path === "/content/sites/uploads" && request.method() === "POST") {
      const body = request.postDataBuffer()?.toString("latin1") ?? "";
      const fields = [...body.matchAll(/name="([a-z_]+)"/g)].map((m) => m[1]!);
      calls.push({ path, fields });
      state = "staged";
      return route.fulfill({ status: 201, json: report() });
    }
    if (path === `/content/sites/${SITE}`) return route.fulfill({ json: detail() });
    if (path === `/content/sites/${SITE}/uploads/${UPLOAD}/report`)
      return route.fulfill({ json: report() });
    if (path === `/content/sites/${SITE}/uploads/${UPLOAD}/release`) {
      calls.push({ path, body: request.postDataJSON() });
      state = "imported";
      return route.fulfill({ json: { job_id: "j1" } });
    }
    return route.fallback();
  });
  await page.route(`**/api/v1/workspaces/${WORKSPACE}/files`, (route) =>
    route.fulfill({
      json: {
        files: [],
        sites:
          state === "imported"
            ? [
                {
                  site: HOST,
                  publisher: "Synthetic Pantry Co",
                  page_count: 3,
                  last_ingested_on: "2026-10-31",
                },
              ]
            : [],
      },
    }),
  );

  // The editor's upload, with the declaration, from the Sites page.
  await page.goto("/content/sites");
  const form = page.getByTestId("upload-crawl");
  await form.getByLabel("Start URL").fill(`https://${HOST}/`);
  await form.getByLabel("Name").fill("Synthetic Pantry");
  await form.getByLabel("Publisher").fill("Synthetic Pantry Co");
  await form.getByLabel("Licence basis").fill("publisher-terms");
  await form.getByRole("checkbox", { name: "sample-web" }).check();
  await form.getByLabel(/ZIP of the crawl/).setInputFiles({
    name: "crawl.zip",
    mimeType: "application/zip",
    buffer: ZIP,
  });
  await form.getByLabel("Crawl date").fill("2026-10-30");
  await form.getByRole("button", { name: "Upload" }).click();
  await expect(form.getByText(/Tick the declaration/)).toBeVisible(); // refused without it
  const declaration = form.getByRole("checkbox", {
    name: `I confirm that this crawl of ${HOST} was made on 2026-10-30`,
  });
  await expect(declaration).not.toBeChecked();
  await declaration.check();
  await form.getByRole("button", { name: "Upload" }).click();
  const shown = form.getByTestId("upload-report");
  await expect(shown).toContainText("3 accepted · 0 refused · 2 skipped");
  await expect(shown).toContainText("site/Products/Gravies.md");
  await expect(page.getByTestId("site-uploaded")).toBeVisible(); // the badge in the list

  // The reviewer releases it from the site page, with the report in front of them.
  await page.goto(`/content/sites/${SITE}`);
  await expect(page.getByRole("button", { name: "Crawl now" })).toHaveCount(0);
  await expect(page.getByText("Approve and crawl")).toHaveCount(0);
  const release = page.getByTestId("release-upload");
  await expect(release.getByTestId("upload-report")).toContainText("site/Recipes/Soup.markdown");
  await release.getByRole("button", { name: "Approve site and release" }).click();
  await expect(page.getByTestId("allow-decision")).toContainText("declared by the uploader");
  for (const path of PAGES) await expect(page.getByText(`https://${HOST}${path}`)).toBeVisible();
  await expect(page.getByTestId("site-uploaded")).toContainText("crawled");
  await expect(page.getByRole("combobox", { name: "Schedule" })).toHaveCount(0);

  // The tenant's library rolls the pages up into one site.
  await page.goto(`/w/${WORKSPACE}/files`);
  await expect(page.getByTestId(`site-${HOST}`)).toContainText("3 pages");

  expect(calls[0]!.path).toBe("/content/sites/uploads");
  expect(calls[0]!.fields).toEqual(
    expect.arrayContaining(["start_url", "tags", "crawled_on", "mode", "file"]),
  );
  expect(calls[0]!.fields).not.toContain("dataset_ids");
  expect(calls[1]).toEqual({
    path: `/content/sites/${SITE}/uploads/${UPLOAD}/release`,
    body: { note: null },
  });
});
