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
});
