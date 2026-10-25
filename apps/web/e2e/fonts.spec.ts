import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS } from "./scenarios/scenarios";

// UX-05: Lato (and Poppins, for the "Mycelium" brand word) is served from our own origin. Nothing the page loads, fonts included, may
// come from another host (the production CSP is `font-src 'self'`), and the font must
// actually be in use, not silently fall back to a system font.
for (const name of ["02-signin-email", "09-chat-long-answer-many-citations"]) {
  test(`fonts load from our origin only: ${name}`, async ({ page, baseURL }) => {
    const requested: string[] = [];
    page.on("request", (request) => requested.push(request.url()));
    const scenario = SCENARIOS.find((s) => s.name === name)!;
    await openScenario(page, scenario);

    const origin = new URL(baseURL!).origin;
    expect(requested.filter((url) => new URL(url).origin !== origin)).toEqual([]);
    expect(requested.some((url) => /\/lato-latin-400-normal[^/]*\.woff2$/.test(url))).toBe(true);
    expect(requested.some((url) => /\/poppins-latin-700-normal[^/]*\.woff2$/.test(url))).toBe(true);
    const loaded = (await page.evaluate(
      "Promise.all(['400 16px Lato', '700 16px Lato', '700 16px Poppins'].map((f) => document.fonts.load(f)))" +
        ".then((sets) => sets.map((s) => s.length))",
    )) as number[];
    expect(
      loaded.every((n) => n > 0),
      "Lato 400 and 700 and Poppins 700 are available",
    ).toBe(true);
  });
}
