import { describe, expect, it } from "vitest";

import { typeLabel } from "./files";

describe("typeLabel (P2B-06)", () => {
  it("names the stored file types, Markdown and text included", () => {
    expect(typeLabel("pdf")).toBe("PDF");
    expect(typeLabel("docx")).toBe("DOCX");
    expect(typeLabel("pptx")).toBe("PPTX");
    expect(typeLabel("markdown")).toBe("Markdown");
    expect(typeLabel("text")).toBe("Text");
  });

  it("falls back to the upper-cased type", () => {
    expect(typeLabel("odt")).toBe("ODT");
  });
});
