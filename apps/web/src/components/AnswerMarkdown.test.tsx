import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConsentNotice } from "../api/types";
import { AnswerMarkdown } from "./AnswerMarkdown";
import { ConsentView } from "./ConsentGate";

const TABLE = "| Role | Mechanism |\n|---|---|\n| Hospital | Tender [1] |\n| GPO | Contracting |";

const answer = (text: string) =>
  renderToString(<AnswerMarkdown text={text} markers={new Set([1])} onCite={() => {}} />);

// P2B-01: GFM tables in answers and in the consent notice.
describe("GFM in answers (P2B-01)", () => {
  it("renders a pipe table as a table with header cells, not as a paragraph", () => {
    const html = answer(TABLE);
    expect(html).toContain("<table");
    expect(html).toMatch(/<th[^>]*scope="col"[^>]*>Role<\/th>/);
    expect(html).toMatch(/<td[^>]*>Hospital<\/td>/);
    expect(html).not.toContain("|---|");
  });

  it("puts the table in a labelled, focusable, sideways-scrolling region", () => {
    const html = answer(TABLE);
    expect(html).toMatch(/<div[^>]*role="region"[^>]*aria-label="Table"[^>]*tabindex="0"/);
    expect(html).toContain("overflow-x-auto");
  });

  it("keeps a citation marker inside a cell as a button", () => {
    const html = answer(TABLE);
    expect(html).toMatch(
      /<td[^>]*>Tender <button[^>]*aria-label="Citation 1"[^>]*>1<\/button><\/td>/,
    );
  });

  it("still shows raw HTML as text and renders no script", () => {
    const html = answer("<script>alert(1)</script>\n\n| a |\n|---|\n| <b>x</b> |");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<b>");
    expect(html.replaceAll("<!-- -->", "")).toContain("&lt;b&gt;x&lt;/b&gt;");
  });

  it("renders strikethrough and read-only task lists", () => {
    const html = answer("~~old~~\n\n- [x] done\n- [ ] open");
    expect(html).toContain("<del>old</del>");
    expect(html.match(/<input[^>]*type="checkbox"[^>]*disabled=""/g)).toHaveLength(2);
  });

  it("opens an autolinked URL in a new tab without opener", () => {
    const html = answer("See https://example.org/a now.");
    expect(html).toMatch(
      /<a[^>]*href="https:\/\/example\.org\/a"[^>]*target="_blank"[^>]*rel="noopener noreferrer"/,
    );
  });
});

describe("GFM in the consent notice (P2B-01)", () => {
  it("renders the notice's table as a table", () => {
    const notice: ConsentNotice = {
      version: "v2",
      title: "Synthetic Notice",
      summary: "Summary.",
      text: "## What we hold\n\n| Data | Kept |\n|---|---|\n| Chats | 30 days |",
      accepted_version: null,
      accepted_at: null,
      required: true,
    };
    const html = renderToString(<ConsentView notice={notice} onAccept={() => {}} />);
    expect(html).toContain("<table");
    expect(html).toMatch(/<th[^>]*>Data<\/th>/);
    expect(html).toMatch(/<td[^>]*>30 days<\/td>/);
  });
});
