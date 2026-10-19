import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("shows the AI notice and the Phase 0 sign-in when there are no credentials", () => {
    const html = renderToString(<App initialMode="phase0" />);
    expect(html).toContain("AI-generated, verify against cited sources.");
    expect(html).toContain("Sign in");
    expect(html).toContain("Access token");
  });

  it("waits for the auth mode before showing a sign-in form", () => {
    const html = renderToString(<App />);
    expect(html).toContain("Loading");
    expect(html).not.toContain("Access token");
  });
});
