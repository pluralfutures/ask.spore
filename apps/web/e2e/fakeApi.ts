import type { Page, Route } from "@playwright/test";

// A stateful fake of /api/v1 for end-to-end tests (Phase 0 auth mode), installed with
// page.route. Synthetic content only (CLAUDE.md): no real documents or queries. It keeps
// what a test needs to assert: every request body the web app sent.

// A saved workspace prompt answers after this long (P1b-13 f).
const SLOW_SAVE_MS = 300;

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

export interface FakeFile {
  id: string;
  type: string;
  title: string;
  publisher: string;
  published_on: string | null;
  canonical_url: string | null;
  ingested_on: string;
  downloadable: boolean;
}

export interface FakeOptions {
  // Files per workspace ID (P1a-14).
  files?: Record<string, FakeFile[]>;
  workspaces: FakeWorkspace[];
  models: FakeModel[];
  // External models fall back to this model, with the notice, as at the spend cap.
  spendCapFallback?: string;
  role?: "user" | "tenant_admin";
  // P1b-10: the user has not accepted the active notice yet; the API refuses until then.
  consentPending?: boolean;
  // P1b-14: the tenant keeps no history (retention 0): conversations are never listed
  // or readable, and each is deleted once its answer is sent.
  noHistory?: boolean;
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
  // Tenant admin routes (P1a-13): saved prompt versions per workspace, and the calls.
  readonly prompts = new Map<string, { version: number; text: string; created_at: string }[]>();
  readonly adminCalls: { method: string; path: string; body: unknown }[] = [];
  readonly downloads: string[] = []; // source IDs whose bytes were served
  private readonly links = new Map<string, string>(); // token -> source ID
  readonly asked: { conversation: string; body: unknown }[] = [];
  private readonly conversations = new Map<string, Conversation>();
  private next = 1;
  readonly accepted: unknown[] = []; // P1b-10: bodies of POST /consent
  private consented: boolean;

  constructor(private readonly options: FakeOptions) {
    this.consented = !options.consentPending;
  }

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
      no_history: Boolean(this.options.noHistory),
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

  private async admin(route: Route, method: string, path: string): Promise<void> {
    const body = route.request().postDataJSON() as unknown;
    this.adminCalls.push({ method, path, body });
    if (this.options.role !== "tenant_admin") {
      return route.fulfill({ status: 403, json: { detail: "forbidden" } });
    }
    if (path === "/admin/users") {
      return route.fulfill({
        json: [
          {
            id: "55555555-5555-4555-8555-555555555555",
            email: "analyst@example.org",
            display_name: "Synthetic Analyst",
            role: "tenant_admin",
            status: "active",
            last_login_at: NOW,
            last_login_method: "sign_in_link",
            created_at: NOW,
          },
        ],
      });
    }
    if (path === "/admin/settings") {
      return route.fulfill({
        json: { retention_days: 30, max_retention_days: 30, answer_modes: ["corpus_only"] },
      });
    }
    const prompt = path.match(/^\/workspaces\/([^/]+)\/prompts?$/);
    if (prompt) {
      const versions = this.prompts.get(prompt[1]) ?? [];
      if (method === "PUT") {
        const saved = {
          workspace_id: prompt[1],
          version: versions.length + 1,
          text: (body as { text: string }).text,
          created_at: NOW,
        };
        this.prompts.set(prompt[1], [saved, ...versions]);
        // Slow on purpose (P1b-13 f): a test that does not wait for the save to land
        // fails every time instead of now and then.
        await new Promise((resolve) => setTimeout(resolve, SLOW_SAVE_MS));
        return route.fulfill({ json: saved });
      }
      return route.fulfill({ json: versions });
    }
    return route.fulfill({ status: 404, json: { detail: "not_found" } });
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
          consent_required: !this.consented,
        },
      });
    }
    if (path === "/consent") {
      if (method === "POST") {
        this.accepted.push(request.postDataJSON());
        this.consented = true;
      }
      return route.fulfill({
        json: {
          version: "v1",
          title: "Synthetic Notice",
          summary: "Synthetic plain-language summary.",
          text: "Synthetic full wording of the notice.",
          accepted_version: this.consented ? "v1" : null,
          accepted_at: this.consented ? NOW : null,
          required: !this.consented,
        },
      });
    }
    if (!this.consented) {
      return route.fulfill({ status: 403, json: { detail: "consent_required" } });
    }
    if (path === "/workspaces") return route.fulfill({ json: this.options.workspaces });
    if (path.startsWith("/admin") || /^\/workspaces\/[^/]+\/prompts?$/.test(path)) {
      return this.admin(route, method, path);
    }
    if (path === "/models") return route.fulfill({ json: this.options.models });
    const files = path.match(/^\/workspaces\/([^/]+)\/files$/);
    if (files) {
      return route.fulfill({
        json: {
          files: this.options.files?.[files[1]] ?? [],
          sites: [
            {
              site: "site.example",
              publisher: "Synthetic Site",
              page_count: 7,
              last_ingested_on: "2026-10-18",
            },
          ],
        },
      });
    }
    const link = path.match(/^\/workspaces\/([^/]+)\/files\/([^/]+)\/download$/);
    if (link && method === "POST") {
      const file = this.options.files?.[link[1]]?.find((f) => f.id === link[2]);
      if (!file) return route.fulfill({ status: 404, json: { detail: "not_found" } });
      if (!file.downloadable) {
        return route.fulfill({ status: 403, json: { detail: "not_downloadable" } });
      }
      const token = `synthetic-token-${this.next++}-abcdefghijklmnop`;
      this.links.set(token, file.id);
      return route.fulfill({
        status: 201,
        json: { url: `/api/v1/files/${token}`, expires_at: NOW },
      });
    }
    const served = path.match(/^\/files\/([^/]+)$/);
    if (served) {
      const sourceId = this.links.get(served[1]);
      this.links.delete(served[1]); // single use
      if (!sourceId) return route.fulfill({ status: 404, json: { detail: "not_found" } });
      this.downloads.push(sourceId);
      return route.fulfill({
        status: 200,
        headers: {
          "content-type": "application/pdf",
          "content-disposition": 'attachment; filename="Synthetic-Outlook-2026.pdf"',
        },
        body: "%PDF-1.4 synthetic",
      });
    }
    if (path === "/conversations" && method === "POST") {
      const body = (request.postDataJSON() ?? {}) as Record<string, unknown>;
      this.created.push(body);
      return route.fulfill({ status: 201, json: this.create(body) });
    }
    if (path === "/conversations") {
      return route.fulfill({
        json: this.options.noHistory ? [] : [...this.conversations.values()].map(summary),
      });
    }
    const ask = path.match(/^\/conversations\/([^/]+)\/messages$/);
    if (ask && method === "POST") {
      const conversation = this.conversations.get(ask[1]);
      if (!conversation) return route.fulfill({ status: 404, json: { detail: "not_found" } });
      const body = request.postDataJSON() as { question: string };
      this.asked.push({ conversation: ask[1], body });
      if (this.options.noHistory) this.conversations.delete(ask[1]);
      return route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream" },
        body: this.answer(conversation, body.question),
      });
    }
    const detail = path.match(/^\/conversations\/([^/]+)$/);
    if (detail) {
      const conversation = this.options.noHistory ? undefined : this.conversations.get(detail[1]);
      return conversation
        ? route.fulfill({ json: conversation })
        : route.fulfill({ status: 404, json: { detail: "not_found" } });
    }
    return route.fulfill({ status: 404, json: { detail: "not_found" } });
  }
}
