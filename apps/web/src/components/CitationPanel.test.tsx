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
});
