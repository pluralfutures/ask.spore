import type { Page, Route } from "@playwright/test";

import * as F from "./fixtures";
import type { Json } from "./fixtures";

// A scenario-configurable fake of /api/v1 for the UX suites (UX-01 to UX-03), installed with
// page.route like fakeApi.ts. Each scenario sets only what differs from the defaults: the
// role, empty lists, a failing or hanging route. Synthetic content only (CLAUDE.md).

export interface Override {
  path: string; // regular expression on the path after /api/v1
  method?: string;
  hang?: boolean; // never answered: the loading state
  status?: number;
  json?: Json;
}

export interface Answer {
  text: string;
  citations: Json[];
  unsupported?: boolean;
  abstained?: boolean;
  failover?: "eu" | "external" | null;
}

export interface ScenarioOptions {
  mode: "phase0" | "oidc";
  signedIn: boolean;
  role: "user" | "tenant_admin";
  operator: boolean;
  consentPending: boolean;
  consentChanged: boolean;
  workspaces: Json[];
  models: Json[];
  conversations: Json[];
  conversationDetail: Record<string, ReturnType<typeof F.conversation>>;
  files: Json[];
  users: Json[];
  prompts: Json[];
  answer: Answer;
  answerError: string | null;
  spendCapNotice: boolean;
  noHistory: boolean;
  feedbackFails: boolean;
  contentRoles: string[] | null;
  contentSources: Json[];
  discover: Json;
  overrides: Override[];
}

export const DEFAULTS: ScenarioOptions = {
  mode: "phase0",
  signedIn: true,
  role: "user",
  operator: false,
  consentPending: false,
  consentChanged: false,
  workspaces: [F.WS_MARKETS],
  models: [F.MODEL_EU],
  conversations: F.CONVERSATION_SUMMARIES,
  conversationDetail: {},
  files: F.FILES,
  users: F.USERS,
  prompts: F.PROMPTS,
  answer: { text: F.SHORT_ANSWER, citations: F.SHORT_CITATIONS },
  answerError: null,
  spendCapNotice: false,
  noHistory: false,
  feedbackFails: false,
  contentRoles: ["content_editor", "content_reviewer"],
  contentSources: F.CONTENT_SOURCES,
  discover: { methods: ["sign_in_link"], sso_kind: null },
  overrides: [],
};

export const CONSENT_SUMMARY =
  "- Answers are **AI-generated** from the research sources your organisation licenses. " +
  "Check them against the cited sources.\n" +
  "- Your questions and answers are kept for at most 30 days, then deleted.\n" +
  "- Questions are processed in the EU unless your organisation enables models served " +
  "outside the EU.";

const CONSENT_TEXT =
  "## 1. What this service is\n\n" +
  "Synthetic paragraph describing processing, retention, sub-processors and rights. ".repeat(10) +
  "\n\n## 2. Your data\n\n" +
  "Synthetic paragraph on personal data and retention. ".repeat(12) +
  "\n\n## 3. Your rights\n\n" +
  "Synthetic paragraph on rights and contacts. ".repeat(10);

const ANSWER_DELAY_MS = 300;

function sse(events: [string, unknown][]): string {
  return events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

export class ScenarioApi {
  readonly options: ScenarioOptions;
  private readonly created = new Map<string, ReturnType<typeof F.conversation>>();
  // Conversations whose first GET has been answered. The chat page loads the conversation
  // and sends the first question at the same time; the fake answers the question only
  // after that load, the order a real API gives, so the title shown at the end is stable.
  private readonly loaded = new Set<string>();
  private consented: boolean;
  private next = 100;

  constructor(options: Partial<ScenarioOptions> = {}) {
    this.options = { ...DEFAULTS, ...options };
    this.consented = !this.options.consentPending;
  }

  async install(page: Page): Promise<void> {
    if (this.options.mode === "phase0" && this.options.signedIn) {
      await page.addInitScript(() => {
        sessionStorage.setItem(
          "askspore.phase0.credentials",
          JSON.stringify({ token: "synthetic-token", email: "analyst@example.org" }),
        );
      });
    }
    await page.route("**/api/v1/**", (route) => this.handle(route));
  }

  private id(prefix: string): string {
    return `${prefix}-0000-4000-8000-${String(this.next++).padStart(12, "0")}`;
  }

  private async handle(route: Route): Promise<void> {
    const o = this.options;
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body });

    for (const override of o.overrides) {
      if (!new RegExp(override.path).test(path)) continue;
      if (override.method && override.method !== method) continue;
      if (override.hang) return; // left unanswered on purpose
      if (override.status)
        return json(override.json ?? { detail: "synthetic_error" }, override.status);
    }

    if (path === "/auth/mode") return json({ mode: o.mode });
    if (path === "/auth/discover") return json(o.discover);
    if (path === "/auth/link") return json({}, 202);
    if (path === "/me") {
      if (o.mode === "oidc" && !o.signedIn) return json({ detail: "unauthorized" }, 401);
      return json({
        email: "analyst@example.org",
        display_name: "Synthetic Analyst",
        role: o.role,
        operator: o.operator,
        tenant_display_name: "Synthetic Client",
        consent_required: !this.consented,
        session_expires_at: null,
      });
    }
    if (path === "/consent") {
      if (method === "POST") this.consented = true;
      return json({
        version: o.consentChanged ? "v2" : "v1",
        title: "Use and privacy notice",
        summary: CONSENT_SUMMARY,
        text: CONSENT_TEXT,
        accepted_version: this.consented
          ? o.consentChanged
            ? "v2"
            : "v1"
          : o.consentChanged
            ? "v1"
            : null,
        accepted_at: this.consented || o.consentChanged ? F.NOW : null,
        required: !this.consented,
      });
    }
    if (!this.consented) return json({ detail: "consent_required" }, 403);
    if (path === "/workspaces") return json(o.workspaces);
    if (path === "/models") return json(o.models);
    if (path === "/conversations" && method === "POST") return this.create(route);
    if (path === "/conversations") return json(o.noHistory ? [] : o.conversations);
    const ask = path.match(/^\/conversations\/([^/]+)\/messages$/);
    if (ask && method === "POST") return this.answer(route, ask[1]);
    if (/^\/messages\/[^/]+\/feedback$/.test(path)) {
      if (o.feedbackFails) return json({ detail: "synthetic_error" }, 500);
      return json({ rating: (request.postDataJSON() as { rating: string }).rating });
    }
    const detail = path.match(/^\/conversations\/([^/]+)$/);
    if (detail) {
      if (method === "DELETE") return route.fulfill({ status: 204 });
      const found = this.created.get(detail[1]) ?? o.conversationDetail[detail[1]];
      this.loaded.add(detail[1]);
      return found && !o.noHistory ? json(found) : json({ detail: "not_found" }, 404);
    }
    if (/^\/workspaces\/[^/]+\/files$/.test(path)) {
      return json({
        files: o.files,
        sites: o.files.length
          ? [
              {
                site: "news.example.org",
                publisher: "Synthetic Trade Observatory",
                page_count: 143,
                last_ingested_on: "2026-10-18",
              },
              {
                site: "council.example.org",
                publisher: "Synthetic Food Systems Council",
                page_count: 1,
                last_ingested_on: "2026-10-11",
              },
            ]
          : [],
      });
    }
    if (path.startsWith("/admin") || /^\/workspaces\/[^/]+\/prompts?$/.test(path)) {
      if (o.role !== "tenant_admin") return json({ detail: "forbidden" }, 403);
      if (path === "/admin/users") return json(o.users);
      if (path === "/admin/settings") {
        return json({
          retention_days: 30,
          max_retention_days: 30,
          answer_modes: ["corpus_only", "general_knowledge"],
        });
      }
      if (path === "/admin/login-policy") return json(F.LOGIN_POLICY);
      if (path.endsWith("/prompts")) {
        return json(path.includes(F.WS_MARKETS.id) ? o.prompts : []);
      }
      return json({ detail: "not_found" }, 404);
    }
    if (path.startsWith("/operator")) return this.operator(route, path);
    if (path.startsWith("/content")) return this.content(route, path, url);
    return json({ detail: "not_found" }, 404);
  }

  private async create(route: Route): Promise<void> {
    const o = this.options;
    const workspace = o.workspaces[0] as typeof F.WS_MARKETS;
    const model = o.models[0] as typeof F.MODEL_EU;
    const id = this.id("11111111");
    const created = F.conversation(id, null, [], {
      workspace_id: workspace.id,
      workspace_name: workspace.name,
    });
    this.created.set(id, created);
    const notice = o.spendCapNotice
      ? "This month's budget for models served outside the EU has been used up. " +
        `This conversation uses ${model.display_name} instead.`
      : null;
    return route.fulfill({
      status: 201,
      json: {
        ...created,
        messages: undefined,
        notice: notice ? "external_spend_cap_reached" : null,
        notice_text: notice,
        no_history: o.noHistory,
      },
    });
  }

  private async answer(route: Route, conversationId: string): Promise<void> {
    const o = this.options;
    const target = this.created.get(conversationId) ?? o.conversationDetail[conversationId];
    const question = (route.request().postDataJSON() as { question: string }).question;
    for (let i = 0; i < 40 && !o.noHistory && !this.loaded.has(conversationId); i++) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    // A real answer takes seconds; answering at once can beat the page's handling of that
    // load, and the page then keeps "New conversation" as the title (backlog, Oct 24).
    await new Promise((resolve) => setTimeout(resolve, ANSWER_DELAY_MS));
    const messageId = this.id("22222222");
    let body: string;
    if (o.answerError) {
      body = sse([
        ["token", { text: "Synthetic capacity grew " }],
        ["error", { error_code: o.answerError }],
      ]);
    } else {
      const a = o.answer;
      const half = Math.floor(a.text.length / 2);
      body = sse([
        ["token", { text: a.text.slice(0, half) }],
        ["token", { text: a.text.slice(half) }],
        ["citations", { citations: a.citations }],
        [
          "done",
          {
            message_id: messageId,
            unsupported: !!a.unsupported,
            abstained: !!a.abstained,
            cached: false,
            tokens_in: 900,
            tokens_out: 120,
            model: "eu-standard",
            reasoning: false,
            truncated: false,
            failover: a.failover ?? null,
          },
        ],
      ]);
      if (target && !o.noHistory) {
        target.title ??= question;
        target.messages.push(
          F.message("user", question),
          F.message("assistant", a.text, {
            id: messageId,
            citations: a.citations,
            unsupported: !!a.unsupported,
            abstained: !!a.abstained,
            failover: a.failover ?? null,
          }),
        );
      }
    }
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body });
  }

  private async operator(route: Route, path: string): Promise<void> {
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body });
    if (!this.options.operator) return json({ detail: "forbidden" }, 403);
    const tenant = `/operator/tenants/${F.TENANT_ID}`;
    if (path === "/operator/tenants") return json(F.TENANTS);
    if (path === "/operator/notices") {
      return json([
        {
          id: "n1",
          created_at: "2026-10-21T08:00:00Z",
          tenant_id: F.TENANT_ID,
          tenant_slug: "alpha",
          kind: "external_spend_50",
        },
        {
          id: "n2",
          created_at: "2026-10-20T08:00:00Z",
          tenant_id: F.TENANT_ID,
          tenant_slug: "beta",
          kind: "workspace_instructions_name_match",
        },
      ]);
    }
    if (path === "/operator/sources") return json(F.OPERATOR_SOURCES);
    if (path === "/operator/terminated-tenants") {
      return json([
        {
          id: "t-gone",
          slug: "gone",
          display_name: "Synthetic Gone",
          status: "suspended",
          purged_at: "2026-10-23T07:56:07Z",
          certificate: "COD-20261023-0000beef",
        },
      ]);
    }
    if (path === "/operator/options") {
      return json({
        answer_modes: ["corpus_only", "general_knowledge"],
        models: ["eu-standard", "eu-fast", "external-large"],
        tags: ["sample-reports", "shared-markets", "alpha-reports"],
      });
    }
    if (path === "/operator/aggregates") return json(F.AGGREGATES);
    if (path === tenant) return json(F.TENANTS[0]);
    if (path === `${tenant}/workspaces`) {
      return json([
        { ...F.WS_MARKETS, tag_ids: ["sample-reports", "alpha-reports"] },
        { ...F.WS_POLICY, tag_ids: ["shared-markets"] },
      ]);
    }
    if (path === `${tenant}/tags`) {
      return json([
        { tag: "alpha-reports", shared: false },
        { tag: "sample-reports", shared: true },
        { tag: "shared-markets", shared: true },
      ]);
    }
    if (path === `${tenant}/users`) return json(this.options.users);
    if (path === `${tenant}/spend`) return json(F.SPEND);
    return json({ detail: "not_found" }, 404);
  }

  private async content(route: Route, path: string, url: URL): Promise<void> {
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body });
    const roles = this.options.contentRoles;
    if (roles === null) return json({ detail: "forbidden" }, 403);
    if (path === "/content/me") return json({ roles, ragflow_ui_url: null });
    if (path === "/content/tags") return json(F.TAGS);
    if (path === "/content/sources") {
      const status = url.searchParams.get("status");
      return json(this.options.contentSources.filter((s) => !status || s.status === status));
    }
    if (path === `/content/sources/${F.SOURCE_DETAIL.id}`) return json(F.SOURCE_DETAIL);
    if (path === "/content/takedowns") return json(F.TAKEDOWNS);
    if (path === "/content/sites") return json(F.SITES);
    if (path === `/content/sites/${F.SITE_ID}`) return json(F.SITE_DETAIL);
    return json({ detail: "not_found" }, 404);
  }
}
