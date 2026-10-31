import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client";
import type { ContentSite, ContentSiteDetail, SiteUpload, UploadReport } from "../../api/types";
import { declarationText, emptyUpload, errorMessage, uploadForm } from "../../lib/content";
import { SiteSummary } from "./SiteDetail";
import { SiteTable, lastCrawl } from "./Sites";
import { ReleaseUpload, SiteUploads, UploadReportView, importCounts } from "./Uploads";

// P2SR01-05: uploaded crawls in the content console. Synthetic rows only (CLAUDE.md).
const ID = "55555555-5555-4555-8555-555555555555";
const UPLOAD = "66666666-6666-4666-8666-666666666666";

const render = (node: ReactNode) =>
  renderToString(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  ).replace(/<!-- -->/g, "");

const site: ContentSite = {
  id: ID,
  name: "Synthetic Pantry",
  start_url: "https://www.example.org/",
  host: "www.example.org",
  publisher: "Synthetic Pantry Co",
  licence_basis: "publisher-terms",
  tags: ["sample-web"],
  status: "approved",
  schedule: "none",
  max_pages: 50,
  allow_decision: "declared",
  allow_checked_at: "2026-10-31T10:00:00Z",
  last_crawl_at: "2026-10-31T10:05:00Z",
  last_crawl_status: "imported",
  next_crawl_at: null,
  page_count: 3,
  blocked_count: 0,
  origin: "upload",
  last_crawled_on: "2026-10-30",
};

const upload = (extra: Partial<SiteUpload> = {}): SiteUpload => ({
  id: UPLOAD,
  status: "imported",
  mode: "partial",
  crawled_on: "2026-10-30",
  uploaded_at: "2026-10-31T09:00:00Z",
  uploaded_by: "editor@example.org",
  released_by: "reviewer@example.org",
  released_at: "2026-10-31T10:00:00Z",
  review_note: "checked",
  error: null,
  member_count: 8,
  accepted_count: 3,
  refused_count: 0,
  skipped_count: 5,
  new_count: 3,
  changed_count: 0,
  unchanged_count: 0,
  blocked_count: 0,
  withdrawn_count: 0,
  ...extra,
});

const detail = (extra: Partial<ContentSiteDetail> = {}): ContentSiteDetail => ({
  ...site,
  allow_patterns: [],
  deny_patterns: [],
  special_category_allow: [],
  review_note: null,
  proposed_by: "editor@example.org",
  approved_by: "reviewer@example.org",
  approved_at: "2026-10-31T10:00:00Z",
  withdrawn_at: null,
  withdrawal_reason: null,
  pages: [],
  jobs: [],
  uploads: [upload()],
  ...extra,
});

const report: UploadReport = {
  upload_id: UPLOAD,
  site_id: ID,
  status: "staged",
  mode: "full",
  crawled_on: "2026-10-30",
  accepted: 2,
  refused: 1,
  skipped: 1,
  would_withdraw: 1,
  members: [
    {
      index: 0,
      name: "site/Products/Gravies.md",
      outcome: "accepted",
      url: "https://www.example.org/Products/Gravies",
      title: "Synthetic Pantry - Gravies",
      published_on: null,
      note: null,
      special_category: null,
    },
    {
      index: 1,
      name: "site/health.md",
      outcome: "accepted",
      url: "https://www.example.org/health/clinic",
      title: "Clinic opening hours",
      published_on: null,
      note: "special_category",
      special_category: "health",
    },
    {
      index: 2,
      name: "site/away.md",
      outcome: "off_site",
      url: null,
      title: null,
      published_on: null,
      note: null,
      special_category: null,
    },
    {
      index: 3,
      name: "site/logo.png",
      outcome: "skipped_not_markdown",
      url: null,
      title: null,
      published_on: null,
      note: null,
      special_category: null,
    },
  ],
};

describe("uploaded crawls", () => {
  it("marks upload sites in the list with their crawl date and no schedule", () => {
    const html = render(<SiteTable sites={[site]} />);
    expect(html).toContain('data-testid="site-uploaded"');
    expect(html).toContain("uploads");
    expect(lastCrawl(site)).toMatch(/^crawled /);
    expect(lastCrawl({ ...site, last_crawled_on: null })).toBe("no upload yet");
    expect(html).toContain("declared by the uploader");
  });

  it("says an upload site is never crawled and has no snapshot", () => {
    const html = render(<SiteSummary site={detail()} />);
    expect(html).toContain("uploaded, no snapshot");
    expect(html).not.toContain("budget 50 pages");
  });

  it("lists the uploads with counts, never file names", () => {
    const html = render(<SiteUploads site={detail()} roles={["content_editor"]} />);
    expect(html).toContain("imported");
    expect(html).toContain("3 of 8");
    expect(html).toContain("reviewer@example.org");
    expect(html).not.toContain("release-upload"); // an editor cannot release
    expect(importCounts(upload())).toBe(
      "3 new · 0 changed · 0 unchanged · 0 blocked · 0 withdrawn",
    );
    expect(importCounts(upload({ status: "staged" }))).toBe("—");
  });

  it("offers the reviewer a release for a staged upload, approving a proposed site", () => {
    const staged = detail({ status: "proposed", uploads: [upload({ status: "staged" })] });
    const html = render(<SiteUploads site={staged} roles={["content_reviewer"]} />);
    expect(html).toContain('data-testid="release-upload"');
    const one = render(<ReleaseUpload site={staged} upload={staged.uploads[0]!} />);
    expect(one).toContain("Approve site and release");
    expect(one).toMatch(/<button[^>]*disabled=""[^>]*>Reject/); // a note is required
  });

  it("shows the report: outcomes, notes and the full upload's withdrawals", () => {
    const html = render(<UploadReportView report={report} />);
    expect(html).toContain("site/Products/Gravies.md");
    expect(html).toContain("will be blocked: special category: health");
    expect(html).toContain("refused: not on the site&#x27;s host");
    expect(html).toContain("skipped: not a Markdown page");
    expect(html).toContain('data-testid="upload-would-withdraw"');
    expect(html).toContain("1 live page missing from this ZIP will be withdrawn");
    const partial = render(<UploadReportView report={{ ...report, would_withdraw: null }} />);
    expect(partial).not.toContain("upload-would-withdraw");
  });

  it("builds the upload form and refuses it without the declaration", () => {
    const zip = new File(["PK"], "crawl.zip", { type: "application/zip" });
    const fields = { ...emptyUpload, crawledOn: "2026-10-30" };
    expect(uploadForm(fields, zip, false)).toEqual({
      error: "Tick the declaration: it is the condition of every upload.",
    });
    expect(uploadForm({ ...fields, declared: true }, null, false)).toHaveProperty("error");
    const existing = uploadForm({ ...fields, declared: true, mode: "full" }, zip, false);
    if (!("form" in existing)) throw new Error("expected a form");
    expect(existing.form.get("mode")).toBe("full");
    expect(existing.form.get("declared_robots_honoured")).toBe("true");
    expect(existing.form.get("start_url")).toBeNull();
    const newSite = { ...fields, declared: true, startUrl: "https://www.example.org/" };
    expect(uploadForm(newSite, zip, true)).toHaveProperty("error"); // name etc. missing
    const full = uploadForm(
      { ...newSite, name: "n", publisher: "p", licenceBasis: "l", tags: ["sample-web"] },
      zip,
      true,
    );
    if (!("form" in full)) throw new Error("expected a form");
    expect(full.form.getAll("tags")).toEqual(["sample-web"]);
    expect(full.form.has("dataset_ids")).toBe(false);
  });

  it("states the declaration word for word", () => {
    expect(declarationText("www.example.org", "2026-10-30")).toBe(
      "I confirm that this crawl of www.example.org was made on 2026-10-30 honouring the " +
        "site's robots.txt, its text-and-data-mining reservation if any, and page-level noai " +
        "and noindex directives, and that the pages are public and were fetched without " +
        "signing in.",
    );
  });

  it("explains a whole-upload refusal by the member's position, not its name", () => {
    expect(errorMessage(new ApiError(422, "duplicate_url", 4))).toBe(
      "Two files in the ZIP give the same page URL. (file 5 in the ZIP)",
    );
    expect(errorMessage(new ApiError(409, "upload_pending"))).toContain("waiting");
  });
});
