import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { rememberWelcomeHidden, WELCOME_KEY, welcomeHidden } from "../lib/welcome";
import { Welcome } from "./Welcome";

function memoryStore() {
  const items = new Map<string, string>();
  return {
    items,
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
  };
}

const throwing = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
};

describe("Welcome (HP-03)", () => {
  it("shows the approved wording, with the step to pick a workspace when there is a choice", () => {
    const html = renderToString(<Welcome workspaceCount={2} onHide={() => {}} />);
    expect(html).toContain("<h1");
    expect(html).toContain("Welcome to");
    expect(html).toContain("SporeBot searches your workspace&#x27;s");
    expect(html).toContain("Pick a workspace");
    expect(html).toContain("Click a number to see the excerpt and where it comes from.");
    expect(html).toContain('aria-label="Hide the welcome"');
  });

  it("leaves the workspace step out with a single workspace", () => {
    const html = renderToString(<Welcome workspaceCount={1} onHide={() => {}} />);
    expect(html).not.toContain("Pick a workspace");
    expect(html).toContain("Ask a specific question");
  });

  it("names no retention longer than 30 days and no corpus-only promise", () => {
    const text = renderToString(<Welcome workspaceCount={2} onHide={() => {}} />).replace(
      /<[^>]+>/g,
      " ",
    );
    for (const days of text.matchAll(/(\d+) days/g))
      expect(Number(days[1])).toBeLessThanOrEqual(30);
    expect(text).not.toMatch(/answers only from|doesn.t know anything outside/i);
  });
});

describe("welcome storage (HP-03)", () => {
  it("remembers Hide under one key holding only a flag", () => {
    const store = memoryStore();
    expect(welcomeHidden(store)).toBe(false);
    rememberWelcomeHidden(store);
    expect(welcomeHidden(store)).toBe(true);
    expect([...store.items.entries()]).toEqual([[WELCOME_KEY, "1"]]);
  });

  it("shows the card and never throws when storage is blocked or missing", () => {
    expect(welcomeHidden(throwing)).toBe(false);
    expect(() => rememberWelcomeHidden(throwing)).not.toThrow();
    expect(welcomeHidden(null)).toBe(false);
    expect(() => rememberWelcomeHidden(null)).not.toThrow();
  });
});
