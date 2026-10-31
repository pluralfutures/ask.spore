import type { ReactNode } from "react";
import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { errorMessage, filtersFromSearch, sourcesForTags } from "../../lib/content";
import { ApiError } from "../../api/client";

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
import { PageTable, ReinstateSite, SiteSummary, WithdrawSite } from "./SiteDetail";
import { SiteTable } from "./Sites";
import { PauseControls, ReplacementChoice, SourceRecord, SourceSummary } from "./SourceDetail";
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
  paused_at: null,
  paused_by: null,
  pause_reason: null,
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

  // UX-21: the facts are a definition list.
  it("lists the source's facts as terms and values", () => {
    const html = render(<SourceSummary source={detail({ licence_file: false })} />);
    expect(html).toContain("<dl");
    for (const term of ["Publisher", "Type", "Published", "Tags", "Status", "Licence basis"]) {
      expect(html).toContain(`>${term}</dt>`);
    }
    expect(html).toMatch(/>Licence file<\/dt><dd[^>]*><span[^>]*>No licence file on record\.</);
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

  // UX-22: the urgency is the badge's colour; its words are the timer's.
  it("shows the timer as a badge coloured by urgency", () => {
    const badge = (days: number) =>
      render(<TakedownTable items={[item(days)]} />).match(
        new RegExp(`<span class="([^"]*)" data-testid="timer-${ID}"`),
      )?.[1];
    expect(badge(-1)).toContain("bg-danger-subtle");
    expect(badge(1)).toContain("bg-warning-muted");
    expect(badge(5)).toContain("bg-neutral-muted");
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
    origin: "crawl",
    last_crawled_on: null,
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
      uploads: [],
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

  it("asks for a note before a withdrawn site is reinstated, never approving it (P2A-12)", () => {
    const empty = render(
      <ReinstateSite note="" onNote={() => {}} onReinstate={() => {}} pending={false} />,
    );
    expect(empty).toMatch(/<button[^>]*disabled=""[^>]*>Reinstate site/);
    expect(empty).toContain("needs a fresh approval");
    expect(empty).not.toContain("Approve");
    const ready = render(
      <ReinstateSite
        note="agreed again"
        onNote={() => {}}
        onReinstate={() => {}}
        pending={false}
      />,
    );
    expect(ready).not.toMatch(/<button[^>]*disabled=""[^>]*>Reinstate site/);
    const busy = render(
      <ReinstateSite note="agreed again" onNote={() => {}} onReinstate={() => {}} pending />,
    );
    expect(busy).toMatch(/<button[^>]*disabled=""[^>]*>Reinstate site/);
  });

  it("shows a reinstated site as proposed and waiting for approval (P2A-12)", () => {
    const reinstated: ContentSiteDetail = {
      ...site,
      status: "proposed",
      allow_patterns: [],
      deny_patterns: [],
      special_category_allow: [],
      review_note: "Publisher agreed again",
      proposed_by: "editor@example.org",
      approved_by: null,
      approved_at: null,
      withdrawn_at: "2026-10-23T10:00:00Z",
      withdrawal_reason: "Publisher asked us to stop",
      next_crawl_at: null,
      pages: [],
      jobs: [],
      uploads: [],
    };
    const html = render(<SiteSummary site={reinstated} />);
    expect(html).toContain('data-testid="site-reinstated"');
    expect(html).toContain("Not crawled until a reviewer approves it again");
    expect(html).toContain("(Publisher asked us to stop)");
    expect(html).not.toContain('data-testid="site-withdrawn"');
    expect(render(<SiteSummary site={{ ...reinstated, withdrawn_at: null }} />)).not.toContain(
      "site-reinstated",
    );
    const pages = render(
      <PageTable
        pages={[
          {
            url: "https://site.example/b",
            state: "removed",
            reason: "reinstated",
            special_category: null,
            source_id: ID,
            published_on: null,
            fetched_at: "2026-10-21T10:00:00Z",
          },
        ]}
      />,
    );
    expect(pages).toContain("taken again at the first crawl after approval");
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

describe("pause (P2A-04)", () => {
  const controls = (status: string, reason: string) =>
    render(
      <PauseControls
        status={status}
        reason={reason}
        onReason={() => {}}
        onPause={() => {}}
        onResume={() => {}}
        pending={false}
      />,
    );

  it("offers nothing on a source that is neither ingested nor paused", () => {
    for (const status of ["proposed", "approved", "failed", "withdrawn", "rejected"])
      expect(controls(status, "r")).toBe("");
  });

  it("asks for a reason before an ingested source can be paused", () => {
    expect(controls("ingested", "")).toMatch(/<button[^>]*disabled=""[^>]*>Pause/);
    const ready = controls("ingested", "rights check");
    expect(ready).not.toMatch(/<button[^>]*disabled=""[^>]*>Pause/);
    expect(ready).toContain("Pause reason");
    expect(ready).toContain("A pause does not answer a takedown.");
    expect(ready).not.toContain("Resume");
  });

  it("offers Resume on a paused source", () => {
    const html = controls("paused", "");
    expect(html).toContain(">Resume<");
    expect(html).not.toContain("Pause reason");
  });

  it("shows the badge and who paused it, when and why", () => {
    const html = render(
      <SourceSummary
        source={detail({
          status: "paused",
          paused_at: "2026-10-25T10:00:00Z",
          paused_by: "reviewer@example.org",
          pause_reason: "Synthetic rights check",
        })}
      />,
    );
    expect(html).toMatch(/data-testid="source-status"[^>]*>paused</);
    expect(html).toContain("by reviewer@example.org: Synthetic rights check");
    expect(render(<SourceSummary source={detail({ status: "ingested" })} />)).not.toContain(
      "pause-record",
    );
  });

  it("lists a paused source with its badge and shows the pause in the history", () => {
    const html = render(<SourceTable sources={[source({ status: "paused" })]} />);
    expect(html).toMatch(/>paused</);
    const record = render(
      <SourceRecord
        source={detail({
          status: "paused",
          history: [
            {
              event: "source.paused",
              at: "2026-10-25T10:00:00Z",
              actor: "reviewer@example.org",
              before: "ingested",
              after: "paused",
              method: null,
            },
            {
              event: "source.resumed",
              at: "2026-10-25T11:00:00Z",
              actor: "reviewer@example.org",
              before: "paused",
              after: "ingested",
              method: null,
            },
          ],
        })}
      />,
    );
    expect(record).toContain("paused (ingested → paused) · reviewer@example.org");
    expect(record).toContain("resumed (paused → ingested) · reviewer@example.org");
  });

  it("links a workspace's tags to the filtered source list and reads them back", () => {
    const href = sourcesForTags(["sample-reports", "sample-web"]);
    expect(href).toBe("/content?tag=sample-reports&tag=sample-web");
    expect(filtersFromSearch(href.slice(href.indexOf("?")))).toEqual({
      tags: ["sample-reports", "sample-web"],
    });
    expect(filtersFromSearch("?status=paused")).toEqual({ status: "paused" });
    expect(sourcesForTags([])).toBe("/content");
  });

  it("explains the pause refusals", () => {
    const refused = (code: string, status = 409) => errorMessage(new ApiError(status, code));
    expect(refused("paused")).toContain("resume it first");
    expect(refused("ingestion_in_progress")).toContain("once it is done");
    expect(refused("ragflow_102", 502)).toBe(
      "RAGFlow refused the change (ragflow_102); nothing was changed.",
    );
    expect(refused("pause_undo_failed", 502)).toContain("datasets sync");
  });
});
