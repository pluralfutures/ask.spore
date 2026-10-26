import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { ModelOption, Workspace } from "../api/types";
import { StartForm } from "./StartForm";

// Synthetic options only (CLAUDE.md).
const WORKSPACE: Workspace = {
  id: "ws-alpha",
  slug: "ws-alpha",
  name: "Alpha team",
  default_mode: "corpus_only",
  default_model: "eu-fast",
  default_reasoning: false,
};
const MODEL: ModelOption = {
  id: "eu-fast",
  display_name: "EU Fast",
  external: false,
  reasoning_switch: true,
  default: true,
};

function render(submitLabel: string, workspaces: Workspace[] | null = [WORKSPACE]): string {
  const client = new QueryClient();
  if (workspaces) client.setQueryData(["workspaces"], workspaces);
  client.setQueryData(["models"], [MODEL]);
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <StartForm submitLabel={submitLabel} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StartForm (HP-01)", () => {
  it("names its submit button by the page's label", () => {
    expect(render("Start")).toContain(">Start</button>");
    expect(render("Ask")).toContain(">Ask</button>");
  });

  it("shows the question, then the settings, and no heading of its own", () => {
    const html = render("Ask");
    expect(html.indexOf("Question")).toBeLessThan(html.indexOf("Settings"));
    expect(html).not.toMatch(/<h[1-6]/);
  });

  it("shows the no-workspace state instead of the form", () => {
    const html = render("Ask", []);
    expect(html).toContain("No workspace has been set up for your organisation yet.");
    expect(html).not.toContain("<form");
  });
});
