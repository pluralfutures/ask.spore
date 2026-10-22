import { expect, test, type Page, type Route } from "@playwright/test";

// P1b-05: the content console against a small fake of /api/v1/content. Synthetic
// register rows only (CLAUDE.md).
const NEW = "33333333-3333-4333-8333-333333333333";
const OLD = "44444444-4444-4444-8444-444444444444";

const row = (id: string, title: string, status: string, replacement: boolean) => ({
  id,
  type: "pdf",
  title,
  publisher: "Synthetic Institute",
  published_on: "2026-03-01",
  canonical_url: "https://example.org/synthetic-outlook",
  licence_basis: "publisher-terms",
  tags: ["sample-reports"],
  status,
  downloadable: false,
  site_id: null,
  takedown_due_on: null,
  possible_replacement: replacement,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-21T10:00:00Z",
});

const SOURCES = [
  row(NEW, "Synthetic Outlook 2026", "proposed", true),
  row(OLD, "Synthetic Outlook 2025", "ingested", false),
];

const detail = {
  ...SOURCES[0],
  review_note: null,
  review_date: null,
  proposed_by: "editor@example.org",
  approved_by: null,
  approved_at: null,
  withdrawn_at: null,
  withdrawal_reason: null,
  chunk_count: null,
  error: null,
  licence_file: false,
  stored: true,
  fetched_at: null,
  supersedes: null,
  possible_replacements: [
    {
      id: OLD,
      title: "Synthetic Outlook 2025",
      publisher: "Synthetic Institute",
      status: "ingested",
    },
  ],
  takedown: null,
  documents: [],
  history: [],
  jobs: [],
};

async function install(page: Page, roles: string[] | null): Promise<unknown[]> {
  const approvals: unknown[] = [];
  await page.addInitScript(() => {
    sessionStorage.setItem(
      "askspore.phase0.credentials",
      JSON.stringify({ token: "synthetic-token", email: "editor@example.org" }),
    );
  });
  await page.route("**/api/v1/**", async (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    if (path === "/auth/mode") return route.fulfill({ json: { mode: "phase0" } });
    if (roles === null) return route.fulfill({ status: 403, json: { detail: "forbidden" } });
    if (path === "/content/me") return route.fulfill({ json: { roles, ragflow_ui_url: null } });
    if (path === "/content/tags") return route.fulfill({ json: [] });
    if (path === "/content/sources") {
      const status = url.searchParams.get("status");
      return route.fulfill({ json: SOURCES.filter((s) => !status || s.status === status) });
    }
    if (path === `/content/sources/${NEW}`) return route.fulfill({ json: detail });
    if (path === `/content/sources/${NEW}/approve`) {
      approvals.push(route.request().postDataJSON());
      return route.fulfill({ json: { job_id: OLD } });
    }
    return route.fulfill({ status: 404, json: { detail: "not_found" } });
  });
  return approvals;
}

test("someone without a content role is told so", async ({ page }) => {
  await install(page, null);
  await page.goto("/content");
  await expect(page.getByText("Content roles only.")).toBeVisible();
});

test("a reviewer filters the register and chooses keep both for a possible replacement", async ({
  page,
}) => {
  const approvals = await install(page, ["content_editor", "content_reviewer"]);
  await page.goto("/content");
  await expect(page.getByTestId(`replacement-${NEW}`)).toBeVisible();
  await page.getByLabel("Status").selectOption("ingested");
  await expect(page.getByRole("link", { name: "Synthetic Outlook 2026" })).toHaveCount(0);
  await page.getByLabel("Status").selectOption("");
  await page.getByRole("link", { name: "Synthetic Outlook 2026" }).click();

  await expect(page.getByTestId("possible-replacement")).toContainText("Synthetic Outlook 2025");
  const approve = page.getByRole("button", { name: "Approve" });
  await expect(approve).toBeDisabled(); // the reviewer must choose first
  await page.getByLabel("Keep both").check();
  await approve.click();
  await expect.poll(() => approvals).toEqual([{ note: null, replaces: null, keep_both: true }]);
});

test("an editor sees no review actions", async ({ page }) => {
  await install(page, ["content_editor"]);
  await page.goto(`/content/sources/${NEW}`);
  await expect(page.getByTestId("source-status")).toHaveText("proposed");
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
});
