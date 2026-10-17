import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("shows the AI notice and sign-in when there are no credentials", () => {
    const html = renderToString(<App />);
    expect(html).toContain("AI-generated, verify against cited sources.");
    expect(html).toContain("Sign in");
  });
});
