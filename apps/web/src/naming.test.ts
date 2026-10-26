import { describe, expect, it } from "vitest";

import indexHtml from "../index.html?raw";

// P1b-17 (owner decision 1 of Oct 22, 2026): the product users see is SporeBot, shown as
// "Mycelium SporeBot" in the page heading and top bar (owner decision, Oct 25, 2026). The
// repository, packages, hostnames and internal names (such as storage keys) stay
// ask.spore / askspore; nothing the web app shows says "ask.spore".
const sources = import.meta.glob<string>(["./**/*.{ts,tsx}", "!./**/*.test.{ts,tsx}"], {
  query: "?raw",
  import: "default",
  eager: true,
});
const OLD_NAME = /ask[.\s]spore/i;

describe("product name", () => {
  it("no web source shows ask.spore", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(20);
    const named = Object.entries(sources)
      .filter(([, text]) => OLD_NAME.test(text))
      .map(([path]) => path);
    expect(named).toEqual([]);
  });

  it("the page title and sign-in heading read SporeBot", () => {
    expect(indexHtml).toContain("<title>SporeBot</title>");
    expect(OLD_NAME.test(indexHtml)).toBe(false);
    // UX-11: every sign-in page shows its heading through the shared card.
    expect(sources["./components/AuthCard.tsx"]).toContain('PRODUCT = "SporeBot"');
    expect(sources["./components/AuthCard.tsx"]).toMatch(/<h1[^>]*>\s*<ProductName \/>\s*<\/h1>/);
    expect(sources["./components/EmailSignIn.tsx"]).toContain("<AuthCard step=");
  });
});
