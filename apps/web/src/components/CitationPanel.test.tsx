import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { Citation } from "../api/types";
import { citationStatus } from "../lib/citations";
import { CitationPanel } from "./CitationPanel";

// Synthetic citations only (CLAUDE.md).
const citation = (marker: number, extra: Partial<Citation> = {}): Citation => ({
  marker,
  source_id: `00000000-0000-4000-8000-00000000000${marker}`,
  chunk_id: `chunk-${marker}`,
  page_or_slide: null,
  excerpt: "Synthetic excerpt.",
  publisher: "Synthetic Publisher",
  title: `Synthetic report ${marker}`,
  published_on: "2026-03-01",
  canonical_url: null,
  type: "pdf",
  superseded: false,
  withdrawn: false,
  unavailable: false,
  ...extra,
});

function render(citations: Citation[]): string {
  return renderToString(<CitationPanel citations={citations} selected={1} onClose={() => {}} />);
}

describe("citation status (P1b-03)", () => {
  it("withdrawn wins over superseded; a live citation has none", () => {
    expect(citationStatus({ superseded: true, withdrawn: true })).toBe("withdrawn");
    expect(citationStatus({ superseded: true })).toBe("superseded");
    expect(citationStatus({})).toBeNull(); // a live answer's citation carries no flags
  });

  it("shows superseded and withdrawn on the citation, and nothing on a current one", () => {
    const html = render([
      citation(1),
      citation(2, { superseded: true }),
      citation(3, { withdrawn: true }),
    ]);
    expect(html).not.toContain('data-testid="citation-status-1"');
    expect(html).toMatch(/data-testid="citation-status-2"[^>]*>superseded</);
    expect(html).toMatch(/data-testid="citation-status-3"[^>]*>withdrawn</);
    expect(html).toContain("A newer version of this source has replaced");
    expect(html).toContain("withdrawn from the research package");
    expect(html).toContain("Synthetic excerpt."); // the stored citation itself stays visible
  });

  it("explains a blanked excerpt and keeps the withdrawn label (any withdrawal)", () => {
    const html = render([citation(1), citation(2, { withdrawn: true, excerpt: "" })]);
    expect(html).toMatch(/data-testid="citation-status-2"[^>]*>withdrawn</);
    expect(html).toContain('data-testid="citation-no-excerpt-2"');
    expect(html).not.toContain('data-testid="citation-no-excerpt-1"');
    expect(html).toContain("The quoted passage was removed because the source was withdrawn.");
    expect(html).not.toContain("licence grounds");
  });

  it("labels a paused source currently unavailable and keeps its excerpt and link (P2A-02)", () => {
    expect(citationStatus({ unavailable: true })).toBe("unavailable");
    expect(citationStatus({ unavailable: true, withdrawn: true })).toBe("withdrawn");
    const html = render([
      citation(1, { unavailable: true, canonical_url: "https://example.org/synthetic" }),
      citation(2),
    ]);
    expect(html).toMatch(/data-testid="citation-status-1"[^>]*>currently unavailable</);
    expect(html).toContain("currently unavailable in the research package");
    expect(html).toContain("Synthetic excerpt."); // D3: a pause keeps the excerpt
    expect(html).not.toContain('data-testid="citation-no-excerpt-1"');
    expect(html).toContain("View at source");
    expect(html).not.toContain('data-testid="citation-status-2"');
  });

  it("drops the label once the source is resumed", () => {
    const html = render([citation(1, { unavailable: false })]);
    expect(html).not.toContain('data-testid="citation-status-1"');
    expect(html).not.toContain("currently unavailable");
  });
});
