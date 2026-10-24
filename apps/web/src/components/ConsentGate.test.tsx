import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConsentNotice } from "../api/types";
import { ConsentView } from "./ConsentGate";

const notice = (extra: Partial<ConsentNotice> = {}): ConsentNotice => ({
  version: "v2",
  title: "Synthetic Notice",
  summary: "Synthetic **summary**.",
  text: "Synthetic full wording.",
  accepted_version: null,
  accepted_at: null,
  required: true,
  ...extra,
});

describe("ConsentView (P1b-10)", () => {
  it("shows the summary and the full notice, and accept starts disabled", () => {
    const html = renderToString(<ConsentView notice={notice()} onAccept={() => {}} />);
    expect(html).toContain("Synthetic Notice");
    expect(html).toContain("In short");
    expect(html).toContain("<strong>summary</strong>");
    expect(html).toContain("Synthetic full wording.");
    expect(html).toContain("before your first conversation");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Accept and continue/);
  });

  it("says when the notice changed since the last acceptance", () => {
    const html = renderToString(
      <ConsentView notice={notice({ accepted_version: "v1" })} onAccept={() => {}} />,
    );
    expect(html).toContain("has changed since you last accepted it");
  });

  it("renders no raw HTML from the notice file", () => {
    const html = renderToString(
      <ConsentView notice={notice({ text: "<script>alert(1)</script>" })} onAccept={() => {}} />,
    );
    expect(html).not.toContain("<script>");
  });

  // UX-12: the notice's structure, under the page's h1 and the "Full notice" h2.
  it("renders the notice's headings below the page's and keeps its lists", () => {
    const html = renderToString(
      <ConsentView
        notice={notice({ text: "# One\n\n## Two\n\n### Three\n\n#### Four\n\n- item" })}
        onAccept={() => {}}
      />,
    );
    expect(html.match(/<h1/g)).toHaveLength(1);
    expect(html).toMatch(/<h3[^>]*>One<\/h3>/);
    expect(html).toMatch(/<h3[^>]*>Two<\/h3>/);
    expect(html).toMatch(/<h3[^>]*>Three<\/h3>/);
    expect(html).toMatch(/<h4[^>]*>Four<\/h4>/);
    expect(html).toContain("<li>item</li>");
    expect(html).toContain("list-disc");
  });

  it("gives the full notice a tab stop", () => {
    const html = renderToString(<ConsentView notice={notice()} onAccept={() => {}} />);
    expect(html).toMatch(/<section aria-labelledby="consent-full" tabindex="0"/);
  });
});
