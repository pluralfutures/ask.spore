import type { Page, Route } from "@playwright/test";

// A stateful fake of /api/v1 for end-to-end tests (Phase 0 auth mode), installed with
// page.route. Synthetic content only (CLAUDE.md): no real documents or queries. It keeps
// what a test needs to assert: every request body the web app sent.

export interface FakeWorkspace {
  id: string;
  slug: string;
  name: string;
  default_mode: string;
  default_model: string;
  default_reasoning: boolean;
}

export interface FakeModel {
  id: string;
  display_name: string;
  external: boolean;
  reasoning_switch: boolean;
  default: boolean;
}

interface Conversation {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string;
  workspace_id: string;
  workspace_name: string;
  mode: string;
  model: string;
  model_display_name: string;
  reasoning: boolean;
  messages: unknown[];
}

export interface FakeOptions {
  workspaces: FakeWorkspace[];
  models: FakeModel[];
  // External models fall back to this model, with the notice, as at the spend cap.
  spendCapFallback?: string;
  role?: "user" | "tenant_admin";
}

// The API's text (app.chat.selection.SPEND_CAP_TEXT).
export function spendCapNotice(model: string): string {
  return (
    "This month's budget for models served outside the EU has been used up. " +
    `This conversation uses ${model} instead.`
  );
}

const NOW = "2026-10-19T10:00:00Z";
const EXPIRES = "2026-11-18T10:00:00Z";

// ConversationSummary: the detail without messages and header labels.
function summary(c: Conversation) {
  return {
    id: c.id,
    title: c.title,
    created_at: c.created_at,
    updated_at: c.updated_at,
    expires_at: c.expires_at,
    workspace_id: c.workspace_id,
    mode: c.mode,
    model: c.model,
    reasoning: c.reasoning,
  };
}

function sse(events: [string, unknown][]): string {
  return events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

export class FakeApi {
  readonly created: unknown[] = [];
  readonly asked: { conversation: string; body: unknown }[] = [];
  private readonly conversations = new Map<string, Conversation>();
  private next = 1;

  constructor(private readonly options: FakeOptions) {}

  private id(prefix: string): string {
    const n = String(this.next++).padStart(12, "0");
    return `${prefix}-0000-4000-8000-${n}`;
  }

  private create(body: Record<string, unknown>): Record<string, unknown> {
    const { workspaces, models, spendCapFallback } = this.options;
    const workspace = workspaces.find((w) => w.id === body.workspace_id) ?? workspaces[0];
    let model = models.find((m) => m.id === (body.model ?? workspace.default_model));
    let notice: string | null = null;
    if (model?.external && spendCapFallback) {
      model = models.find((m) => m.id === spendCapFallback);
      notice = model ? spendCapNotice(model.display_name) : null;
    }
    if (!model) throw new Error("fake: unknown model");
    const reasoning =
      Boolean(body.reasoning ?? workspace.default_reasoning) && model.reasoning_switch;
    const conversation: Conversation = {
      id: this.id("11111111"),
      title: null,
      created_at: NOW,
      updated_at: NOW,
      expires_at: EXPIRES,
      workspace_id: workspace.id,
      workspace_name: workspace.name,
      mode: workspace.default_mode,
      model: model.id,
      model_display_name: model.display_name,
      reasoning,
      messages: [],
    };
    this.conversations.set(conversation.id, conversation);
    return {
      ...summary(conversation),
      notice: notice ? "external_spend_cap_reached" : null,
      notice_text: notice,
    };
  }

  private answer(conversation: Conversation, question: string): string {
    const messageId = this.id("22222222");
    const text = "Synthetic capacity grew by 12% in 2025 [1].";
    const citation = {
      marker: 1,
      source_id: "33333333-3333-4333-8333-333333333333",
      chunk_id: "chunk-synthetic-1",
      page_or_slide: 4,
      excerpt: "Synthetic capacity grew by 12 percent in 2025.",
      publisher: "Synthetic Institute",
      title: "Synthetic Outlook 2026",
      published_on: "2026-03-01",
      canonical_url: "https://example.org/synthetic-outlook",
      type: "pdf",
    };
    conversation.title ??= question;
    conversation.messages.push(
      {
        id: this.id("44444444"),
        role: "user",
        content: question,
        mode: conversation.mode,
        created_at: NOW,
        unsupported: false,
        abstained: false,
        citations: [],
      },
      {
        id: messageId,
        role: "assistant",
        content: text,
        mode: conversation.mode,
        created_at: NOW,
        unsupported: false,
        abstained: false,
        citations: [citation],
        model: conversation.model,
        reasoning: conversation.reasoning,
      },
    );
    return sse([
      ["token", { text: "Synthetic capacity grew by 12% " }],
      ["token", { text: "in 2025 [1]." }],
      ["citations", { citations: [citation] }],
      [
        "done",
        {
          message_id: messageId,
          unsupported: false,
          abstained: false,
          cached: false,
          tokens_in: 900,
          tokens_out: 12,
          model: conversation.model,
          reasoning: conversation.reasoning,
        },
      ],
    ]);
  }

  async install(page: Page): Promise<void> {
    await page.addInitScript(() => {
      sessionStorage.setItem(
        "askspore.phase0.credentials",
        JSON.stringify({ token: "synthetic-token", email: "analyst@example.org" }),
      );
    });
    await page.route("**/api/v1/**", (route) => this.handle(route));
  }

  private async handle(route: Route): Promise<void> {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    if (path === "/auth/mode") return route.fulfill({ json: { mode: "phase0" } });
    if (path === "/me") {
      return route.fulfill({
        json: {
          email: "analyst@example.org",
          display_name: "Synthetic Analyst",
          role: this.options.role ?? "user",
          tenant_display_name: "Synthetic Client",
        },
      });
    }
    if (path === "/workspaces") return route.fulfill({ json: this.options.workspaces });
    if (path === "/models") return route.fulfill({ json: this.options.models });
    if (path === "/conversations" && method === "POST") {
      const body = (request.postDataJSON() ?? {}) as Record<string, unknown>;
      this.created.push(body);
      return route.fulfill({ status: 201, json: this.create(body) });
    }
    if (path === "/conversations") {
      return route.fulfill({
        json: [...this.conversations.values()].map(summary),
      });
    }
    const ask = path.match(/^\/conversations\/([^/]+)\/messages$/);
    if (ask && method === "POST") {
      const conversation = this.conversations.get(ask[1]);
      if (!conversation) return route.fulfill({ status: 404, json: { detail: "not_found" } });
      const body = request.postDataJSON() as { question: string };
      this.asked.push({ conversation: ask[1], body });
      return route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream" },
        body: this.answer(conversation, body.question),
      });
    }
    const detail = path.match(/^\/conversations\/([^/]+)$/);
    if (detail) {
      const conversation = this.conversations.get(detail[1]);
      return conversation
        ? route.fulfill({ json: conversation })
        : route.fulfill({ status: 404, json: { detail: "not_found" } });
    }
    return route.fulfill({ status: 404, json: { detail: "not_found" } });
  }
}
