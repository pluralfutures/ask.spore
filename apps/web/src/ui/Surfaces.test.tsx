import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Badge, StatusBadge } from "./Badge";
import { Card } from "./Card";
import { Notice } from "./Notice";
import { PageHeader } from "./PageHeader";
import { EmptyState, Loading, Skeleton } from "./States";

describe("surfaces and feedback (UX-08)", () => {
  it("a status badge shows the status word unchanged, coloured by its tone", () => {
    const html = renderToString(<StatusBadge kind="source" status="failed" />);
    expect(html).toContain(">failed</span>");
    expect(html).toContain("bg-danger-subtle");
    expect(renderToString(<StatusBadge kind="user" status="brand-new" />)).toContain(
      "bg-neutral-muted",
    );
    expect(renderToString(<Badge tone="success">ok</Badge>)).toContain("rounded-badge");
  });

  it("a notice adds an icon but no words, and keeps role and test id", () => {
    const html = renderToString(
      <Notice tone="warning" role="status" data-testid="n">
        Exact text.
      </Notice>,
    );
    expect(html).toMatch(/^<div[^>]*role="status"/);
    expect(html).toContain('data-testid="n"');
    expect(html).toMatch(/<svg[^>]*aria-hidden="true"/);
    expect(html.replace(/<[^>]+>/g, "")).toBe("Exact text.");
  });

  it("a card has a border, no shadow, and its title as a heading", () => {
    const html = renderToString(
      <Card title="Users" level={3}>
        x
      </Card>,
    );
    expect(html).toMatch(/^<section class="[^"]*rounded-card border/);
    expect(html).not.toContain("shadow");
    expect(html).toContain("<h3");
  });

  it("the page header has the one h1 and an optional back link", () => {
    const html = renderToString(
      <MemoryRouter>
        <PageHeader title="Administration" back={{ to: "/", label: "← Conversations" }} />
      </MemoryRouter>,
    );
    expect(html.match(/<h1/g)).toHaveLength(1);
    expect(html).toContain("← Conversations</a>");
  });

  it("loading states announce themselves; their spinners are hidden", () => {
    const loading = renderToString(<Loading />);
    expect(loading).toMatch(/role="status"/);
    expect(loading).toContain("Loading…");
    expect(loading).toMatch(/<svg[^>]*aria-hidden="true"/);
    expect(renderToString(<Skeleton />)).toMatch(/role="status".*sr-only">Loading…/);
  });

  it("an empty state shows the page's own sentence", () => {
    expect(renderToString(<EmptyState title="No conversations yet." />)).toContain(
      "No conversations yet.",
    );
  });
});
