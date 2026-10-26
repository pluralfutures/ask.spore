import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { DOCUMENTS, consentVersionLine, render, versionOf } from "./render-legal.mjs";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "../public/legal");

describe("legal pages (P2A-L2)", () => {
  it("are generated from design/compliance and up to date", async () => {
    const pages = await render();
    expect(pages.size).toBe(DOCUMENTS.length);
    for (const [doc, { html }] of pages) {
      expect(readFileSync(join(OUT, `${doc.slug}.html`), "utf8"), doc.slug).toBe(html);
    }
  });

  it("are static: no script, no external resource, no form", () => {
    for (const name of ["index", "privacy", "ai", "terms"]) {
      const html = readFileSync(join(OUT, `${name}.html`), "utf8");
      expect(html, name).not.toMatch(/<script|<form|<iframe|<img/i);
      expect(html, name).not.toMatch(/(src|href)="https?:\/\/(?!askspore\.)/i);
      expect(html, name).toContain('<link rel="stylesheet" href="/public-page.css" />');
    }
  });

  it("index lists the three documents", () => {
    const html = readFileSync(join(OUT, "index.html"), "utf8");
    for (const path of ["/legal/privacy", "/legal/ai", "/legal/terms"]) {
      expect(html).toContain(`href="${path}"`);
    }
  });
});

describe("version match (P2A-L2, release check)", () => {
  it("reads the version token of a notice", () => {
    expect(versionOf("Intro\n\nVersion 3, Oct 26, 2026.")).toBe("3");
    expect(versionOf("Version [version], last updated [date].")).toBe("[version]");
    expect(versionOf("no version here")).toBeNull();
  });

  it("finds the notice the gate shows", () => {
    const { file, version } = consentVersionLine();
    expect(file).toMatch(/^v\d+\.md$/);
    expect(version).not.toBeNull();
  });
});
