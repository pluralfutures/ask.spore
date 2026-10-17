import { describe, expect, it } from "vitest";

import { linkMarkers, markerFromHref, splitMarkers } from "./citations";

describe("splitMarkers", () => {
  it("splits text and valid markers", () => {
    expect(splitMarkers("Grew [1] and fell [2].", new Set([1, 2]))).toEqual([
      { kind: "text", text: "Grew " },
      { kind: "marker", marker: 1 },
      { kind: "text", text: " and fell " },
      { kind: "marker", marker: 2 },
      { kind: "text", text: "." },
    ]);
  });

  it("handles adjacent markers and markers at the edges", () => {
    expect(splitMarkers("[1][3]", new Set([1, 3]))).toEqual([
      { kind: "marker", marker: 1 },
      { kind: "marker", marker: 3 },
    ]);
  });

  it("leaves markers without a citation and non-marker brackets as text", () => {
    expect(splitMarkers("See [4], [sic] and [2025 data].", new Set([1]))).toEqual([
      { kind: "text", text: "See [4], [sic] and [2025 data]." },
    ]);
  });

  it("returns nothing for empty text", () => {
    expect(splitMarkers("", new Set([1]))).toEqual([]);
  });
});

describe("linkMarkers", () => {
  it("turns valid markers into cite links", () => {
    expect(linkMarkers("Grew [1], not [9].", new Set([1]))).toBe(
      "Grew [\\[1\\]](#cite-1), not [9].",
    );
  });
});

describe("markerFromHref", () => {
  it("reads cite links only", () => {
    expect(markerFromHref("#cite-3")).toBe(3);
    expect(markerFromHref("#cite-0")).toBeNull();
    expect(markerFromHref("#cite-x")).toBeNull();
    expect(markerFromHref("https://example.org/#cite-1")).toBeNull();
    expect(markerFromHref(undefined)).toBeNull();
  });
});
