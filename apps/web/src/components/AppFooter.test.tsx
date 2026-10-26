import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AppFooter, LEGAL_PATH } from "./AppFooter";

describe("AppFooter (P2A-L1)", () => {
  const html = renderToStaticMarkup(<AppFooter />);

  it("is a footer landmark with one Legal link to the static legal page", () => {
    expect(html.startsWith("<footer")).toBe(true);
    expect(html.match(/<a /g)).toHaveLength(1);
    expect(html).toContain(`href="${LEGAL_PATH}"`);
    expect(html).toContain("Legal");
    expect(html).toContain('aria-label="Legal"');
  });

  it("opens in a new tab without an opener and says so", () => {
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener"');
    expect(html).toContain("(opens in a new tab)");
  });

  it("carries nothing that names a tenant or a user (P2A-L3)", () => {
    expect(LEGAL_PATH).toBe("/legal");
    expect(html).not.toMatch(/[?#]/);
  });
});
