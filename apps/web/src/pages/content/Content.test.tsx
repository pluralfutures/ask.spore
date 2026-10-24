import type { ReactNode } from "react";
import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type {
  ContentSite,
  ContentSiteDetail,
  ContentSource,
  ContentSourceDetail,
  ContentTag,
  Takedown,
} from "../../api/types";
import { ProposeResult } from "./Propose";
import { SourceTable } from "./Register";
import { PageTable, SiteSummary, WithdrawSite } from "./SiteDetail";
import { SiteTable } from "./Sites";
import { ReplacementChoice, SourceRecord, SourceSummary } from "./SourceDetail";
import { TagTable } from "./Tags";
import { TakedownTable } from "./Takedowns";

// Synthetic register rows only (CLAUDE.md).
const ID = "33333333-3333-4333-8333-333333333333";
const OLD = "44444444-4444-4444-8444-444444444444";

const source = (extra: Partial<ContentSource> = {}): ContentSource => ({
  id: ID,
  type: "pdf",
  title: "Synthetic Outlook 2026",
  publisher: "Synthetic Institute",
  published_on: "2026-03-01",
  canonical_url: "https://example.org/synthetic-outlook",
  licence_basis: "publisher-terms",
  tags: ["sample-reports"],
  status: "proposed",
  downloadable: false,
  site_id: null,
  takedown_due_on: null,
  possible_replacement: false,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-21T10:00:00Z",
  ...extra,
});

const detail = (extra: Partial<ContentSourceDetail> = {}): ContentSourceDetail => ({
  ...source(),
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
  possible_replacements: [],
  takedown: null,
  documents: [],
  history: [],
  jobs: [],
  ...extra,
});

// Server rendering marks text boundaries with <!-- -->; the assertions read the text.
function render(node: ReactNode): string {
  return renderToString(<MemoryRouter>{node}</MemoryRouter>).replace(/<!-- -->/g, "");
}

describe("register list", () => {
  it("links each source and flags possible replacements and takedowns", () => {
    const html = render(
      <SourceTable
        sources={[
          source({ possible_replacement: true }),
          source({
            id: OLD,
            status: "ingested",
            takedown_due_on: "2026-11-04",
            type: "markdown",
            site_id: ID,
          }),
        ]}
      />,
    );
    expect(html).toContain(`href="/content/sources/${ID}"`);
    expect(html).toContain(`data-testid="replacement-${ID}"`);
    expect(html).not.toContain(`data-testid="replacement-${OLD}"`);
    expect(html).toContain("takedown");
    expect(html).toContain("web page");
  });

  it("says so when nothing matches", () => {
    expect(render(<SourceTable sources={[]} />)).toContain("No sources match");
  });
});

describe("source detail", () => {
  it("shows status, the ingestion error, the licence file and the takedown timer", () => {
    const html = render(
      <SourceSummary
        source={detail({
          status: "failed",
          error: "parse_failed: synthetic parser message",
          licence_file: true,
          takedown: {
            source_id: ID,
            title: "Synthetic Outlook 2026",
            status: "failed",
            reference: "TD-2026-1",
            requested_on: "2026-10-20",
            due_on: "2026-11-03",
            working_days_left: -2,
            licence_grounds: true,
          },
        })}
      />,
    );
    expect(html).toMatch(/data-testid="source-status"[^>]*>failed</);
    expect(html).toContain("synthetic parser message");
    expect(html).toContain(`href="/api/v1/content/sources/${ID}/licence"`);
    expect(html).toContain("2 working days overdue");
    expect(html).toContain("licence grounds");
  });

  it("names possible replacements and offers replace or keep both", () => {
    const candidates = [
      {
        id: OLD,
        title: "Synthetic Outlook 2025",
        publisher: "Synthetic Institute",
        status: "ingested",
      },
    ];
    const summary = render(
      <SourceSummary source={detail({ possible_replacements: candidates })} />,
    );
    expect(summary).toContain("Possible replacement of");
    expect(summary).toContain("Synthetic Outlook 2025");
    const choice = render(
      <ReplacementChoice candidates={candidates} value="" onChange={() => {}} />,
    );
    expect(choice).toContain(`value="${OLD}"`);
    expect(choice).toContain("Replace Synthetic Outlook 2025");
    expect(choice).toContain("Keep both");
  });

  it("links documents to the loopback RAGFlow UI and lists history and jobs", () => {
    const html = render(
      <SourceRecord
        source={detail({
          documents: [
            {
              tag: "sample-reports",
              dataset_id: "d1",
              document_id: "doc1",
              ragflow_url: "http://127.0.0.1:8080/chunk/parsed/chunks?id=d1&doc_id=doc1",
            },
          ],
          history: [
            {
              event: "source.proposed",
              at: "2026-10-20T10:00:00Z",
              actor: "editor@example.org",
              before: null,
              after: "proposed",
              method: "editor",
            },
          ],
          jobs: [
            {
              id: OLD,
              type: "ingest_source",
              status: "failed",
              error_code: "parse_failed",
              attempts: 1,
              created_at: "2026-10-20T10:00:00Z",
              finished_at: null,
            },
          ],
        })}
      />,
    );
    expect(html).toContain(
      'href="http://127.0.0.1:8080/chunk/parsed/chunks?id=d1&amp;doc_id=doc1"',
    );
    expect(html).toContain("SSH tunnel");
    expect(html).toContain("proposed (new → proposed) · editor@example.org");
    // UX-08: the job status is a badge; the words are unchanged.
    expect(html.replace(/<[^>]+>/g, "")).toContain("ingest_source · failed · parse_failed");
  });
});

describe("propose result", () => {
  it("explains the outcome and a possible replacement", () => {
    const html = render(
      <ProposeResult
        result={{
          source_id: ID,
          outcome: "proposed",
          status: "proposed",
          possible_replacements: [
            {
              id: OLD,
              title: "Synthetic Outlook 2025",
              publisher: "Synthetic Institute",
              status: "ingested",
            },
          ],
        }}
      />,
    );
    expect(html).toContain("waits for a reviewer");
    expect(html).toContain("replace or keep both");
    const taken = render(
      <ProposeResult
        result={{
          source_id: ID,
          outcome: "taken_down",
          status: "withdrawn",
          possible_replacements: [],
        }}
      />,
    );
    expect(taken).toContain("takedown request");
    expect(taken).not.toContain('data-testid="propose-replaces"');
  });

  it("says which source a same-link, same-title proposal replaces (decision 3)", () => {
    const html = render(
      <ProposeResult
        result={{
          source_id: ID,
          outcome: "proposed",
          status: "proposed",
          possible_replacements: [],
          replaces: {
            id: OLD,
            title: "Synthetic Outlook 2025",
            publisher: "Synthetic Institute",
            status: "ingested",
          },
        }}
      />,
    );
    expect(html).toContain('data-testid="propose-replaces"');
    expect(html).toContain("it replaces that source");
    expect(html).not.toContain("replace or keep both");
  });
});

describe("takedown queue", () => {
  const item = (days: number): Takedown => ({
    source_id: ID,
    title: "Synthetic Outlook 2026",
    status: "ingested",
    reference: "TD-2026-1",
    requested_on: "2026-10-20",
    due_on: "2026-11-03",
    working_days_left: days,
    licence_grounds: false,
  });

  it("shows the SLA timer per request", () => {
    expect(render(<TakedownTable items={[item(4)]} />)).toMatch(
      new RegExp(`data-testid="timer-${ID}"[^>]*>(?:<div[^>]*>)?4 working days left<`),
    );
    expect(render(<TakedownTable items={[item(-1)]} />)).toContain("text-danger");
    expect(render(<TakedownTable items={[]} />)).toContain("No open takedown requests");
  });
});

describe("sites", () => {
  const site: ContentSite = {
    id: ID,
    name: "Synthetic Energy Institute",
    start_url: "https://site.example/",
    host: "site.example",
    publisher: "Synthetic Energy Institute",
    licence_basis: "publisher-terms",
    tags: ["sample-web"],
    status: "approved",
    schedule: "weekly",
    max_pages: 50,
    allow_decision: "tdm_reserved",
    allow_checked_at: "2026-10-21T10:00:00Z",
    last_crawl_at: "2026-10-21T10:00:00Z",
    last_crawl_status: "tdm_reserved",
    next_crawl_at: "2026-10-28T10:00:00Z",
    page_count: 0,
    blocked_count: 2,
  };

  it("lists sites with their allow decision, last crawl and blocked count", () => {
    const html = render(<SiteTable sites={[site]} />);
    expect(html).toContain(`href="/content/sites/${ID}"`);
    expect(html).toContain("text-and-data mining reserved");
    expect(html).toContain("tdm_reserved");
  });

  it("shows a site's scope and its pages, blocked ones with the reason", () => {
    const full: ContentSiteDetail = {
      ...site,
      allow_patterns: ["/reports/*"],
      deny_patterns: ["/reports/draft-*"],
      special_category_allow: [],
      review_note: null,
      proposed_by: "editor@example.org",
      approved_by: "editor@example.org",
      approved_at: "2026-10-20T10:00:00Z",
      withdrawn_at: null,
      withdrawal_reason: null,
      pages: [],
      jobs: [],
    };
    expect(render(<SiteSummary site={full} />)).toContain(
      "crawl /reports/*; never /reports/draft-*",
    );
    expect(render(<SiteSummary site={full} />)).not.toContain('data-testid="site-withdrawn"');
    const retired = render(
      <SiteSummary
        site={{
          ...full,
          status: "withdrawn",
          withdrawn_at: "2026-10-23T10:00:00Z",
          withdrawal_reason: "Publisher asked us to stop",
          next_crawl_at: null,
        }}
      />,
    );
    expect(retired).toContain('data-testid="site-withdrawn"');
    expect(retired).toContain("Publisher asked us to stop");
    expect(retired).toContain("Never crawled");
    const pages = render(
      <PageTable
        pages={[
          {
            url: "https://site.example/a",
            state: "live",
            reason: null,
            special_category: null,
            source_id: ID,
            published_on: "2026-02-10",
            fetched_at: "2026-10-21T10:00:00Z",
          },
          {
            url: "https://site.example/health/clinic",
            state: "blocked",
            reason: "special_category",
            special_category: "health",
            source_id: null,
            published_on: null,
            fetched_at: "2026-10-21T10:00:00Z",
          },
        ]}
      />,
    );
    expect(pages).toContain(`href="/content/sources/${ID}"`);
    expect(pages).toContain("special category: health");
    expect(pages).toContain("10 Feb 2026");
    const reasons = render(
      <PageTable
        pages={["site_withdrawn", "restored"].map((reason) => ({
          url: `https://site.example/${reason}`,
          state: reason === "restored" ? "removed" : "blocked",
          reason,
          special_category: null,
          source_id: ID,
          published_on: null,
          fetched_at: "2026-10-21T10:00:00Z",
        }))}
      />,
    );
    expect(reasons).toContain("the whole site was withdrawn");
    expect(reasons).toContain("taken again at the next crawl");
  });

  it("asks for a reason before a site can be withdrawn (P1c-14)", () => {
    const empty = render(
      <WithdrawSite reason="" onReason={() => {}} onWithdraw={() => {}} pending={false} />,
    );
    expect(empty).toContain("Withdraw site");
    expect(empty).toMatch(/<button[^>]*disabled=""[^>]*>Withdraw site/);
    const ready = render(
      <WithdrawSite reason="retired" onReason={() => {}} onWithdraw={() => {}} pending={false} />,
    );
    expect(ready).not.toMatch(/<button[^>]*disabled=""[^>]*>Withdraw site/);
    expect(ready).toContain("never crawled again");
  });
});

describe("tags", () => {
  it("shows the tag-to-dataset mapping, unsynced tags and the RAGFlow link", () => {
    const tags: ContentTag[] = [
      {
        tag: "sample-web",
        chunk_method: "naive",
        chunk_method_by_type: {},
        dataset_id: "d1",
        ragflow_url: "http://127.0.0.1:8080/dataset/dataset/d1",
        sources: 3,
      },
      {
        tag: "sample-reports",
        chunk_method: "paper",
        chunk_method_by_type: { pptx: "presentation" },
        dataset_id: null,
        ragflow_url: null,
        sources: 0,
      },
    ];
    const html = render(<TagTable tags={tags} />);
    expect(html).toContain('href="http://127.0.0.1:8080/dataset/dataset/d1"');
    expect(html).toContain("not synced");
    expect(html).toContain("pptx: presentation");
  });
});
