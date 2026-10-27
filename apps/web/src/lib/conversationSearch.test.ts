import { describe, expect, it } from "vitest";

import { matchesTitle } from "./conversationSearch";

describe("conversation search (P2B-03)", () => {
  it("matches every title when the query is empty or only spaces", () => {
    expect(matchesTitle("Synthetic outlook", "")).toBe(true);
    expect(matchesTitle("Synthetic outlook", "   ")).toBe(true);
    expect(matchesTitle(null, "")).toBe(true);
  });

  it("ignores case, accents and repeated spaces", () => {
    expect(matchesTitle("Café menu trends", "CAFE  menu")).toBe(true);
    expect(matchesTitle("Cafe menu trends", "café")).toBe(true);
  });

  it("matches part of a title and rejects other titles", () => {
    expect(matchesTitle("Synthetic outlook 2026", "outlook")).toBe(true);
    expect(matchesTitle("Synthetic outlook 2026", "forecast")).toBe(false);
  });

  it("finds an untitled conversation by the words shown for it", () => {
    expect(matchesTitle(null, "untitled")).toBe(true);
    expect(matchesTitle(null, "outlook")).toBe(false);
  });
});
