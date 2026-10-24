import type { Page } from "@playwright/test";

import * as F from "./fixtures";
import type { ScenarioOptions } from "./scenarioApi";

// Every route and key state of the web app, as captured in design/ux/audit.md. The visual
// suite (UX-01) screenshots each one at both widths; the accessibility and layout baseline
// (UX-02) checks each one. Names match the audit's screenshot files.

export interface Scenario {
  name: string;
  url: string;
  options?: Partial<ScenarioOptions>;
  // Brings the page into the state; resolves once that state is on screen.
  act?: (page: Page) => Promise<void>;
}

export const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  phone: { width: 390, height: 844 },
} as const;

const C = (n: number) => `11111111-0000-4000-8000-0000000009${String(n).padStart(2, "0")}`;
export const LONG_CONVERSATION = C(1);
export const NOTES_CONVERSATION = C(2);

const LONG_QUESTION =
  "What drove synthetic fertiliser prices in 2025, and what should a business development " +
  "team expect in the synthetic south region next season?";

// Built per call: a scenario's fake appends to its conversations.
export function conversationDetails(): ScenarioOptions["conversationDetail"] {
  return {
    [C(1)]: F.conversation(
      C(1),
      LONG_QUESTION,
      [
        F.message("user", LONG_QUESTION),
        F.message("assistant", F.LONG_ANSWER, { citations: F.MANY_CITATIONS }),
      ],
      { reasoning: true, workspace_name: F.WS_POLICY.name },
    ),
    [C(2)]: F.conversation(
      C(2),
      "Synthetic cocoa in the synthetic west",
      [
        F.message("user", "Synthetic cocoa in the synthetic west"),
        F.message(
          "assistant",
          "None of your sources covers synthetic cocoa production in the synthetic west " +
            "region. Try a broader question or ask your administrator which sources this " +
            "workspace includes.",
          { abstained: true },
        ),
        F.message("user", "What about general synthetic cocoa prices?"),
        F.message(
          "assistant",
          "Synthetic cocoa prices rose sharply in 2024, but none of your sources supports " +
            "this statement directly.",
          { unsupported: true },
        ),
        F.message("user", "Give me the full synthetic regional breakdown"),
        F.message(
          "assistant",
          "The synthetic regional breakdown starts with the north region, where",
          { partial: true },
        ),
        F.message("user", "And the synthetic export figures?"),
        F.message("assistant", "Synthetic exports rose by 3% [1].", {
          citations: [F.citation(1, { withdrawn: true, excerpt: "" })],
          failover: "external",
          truncated: true,
        }),
      ],
      { mode: "general_knowledge" },
    ),
  };
}

export async function askFirstQuestion(
  page: Page,
  question = "What drove synthetic capacity growth in 2025?",
): Promise<void> {
  await page.getByLabel("Question").fill(question);
  await page.getByRole("button", { name: "Start" }).click();
}

// Done once the reloaded conversation holds the answer and its title.
async function answered(page: Page): Promise<void> {
  const question = "What drove synthetic capacity growth in 2025?";
  await askFirstQuestion(page, question);
  await page.getByRole("button", { name: "Helpful", exact: true }).waitFor();
  await page.getByRole("heading", { level: 1, name: question }).waitFor();
}

const CHOICES: Partial<ScenarioOptions> = {
  workspaces: [F.WS_MARKETS, F.WS_POLICY],
  models: [F.MODEL_EU, F.MODEL_FAST, F.MODEL_EXT],
};
const ADMIN: Partial<ScenarioOptions> = { ...CHOICES, role: "tenant_admin", operator: true };
// Content staff: the fake gives no content roles unless a scenario asks (UX-10: the top bar
// links the content console only for them).
const CONTENT: Partial<ScenarioOptions> = { contentRoles: ["content_editor", "content_reviewer"] };
const FILES = `/w/${F.WS_MARKETS.id}/files`;
const TENANT = `/operator/tenants/${F.TENANT_ID}`;

export const SCENARIOS: Scenario[] = [
  { name: "01-signin-token", url: "/", options: { signedIn: false } },
  { name: "02-signin-email", url: "/", options: { mode: "oidc", signedIn: false } },
  {
    name: "02b-signin-email-sso-failed",
    url: "/?sign_in=failed&reason=not_provisioned",
    options: { mode: "oidc", signedIn: false },
  },
  {
    name: "02c-signin-email-sent",
    url: "/",
    options: { mode: "oidc", signedIn: false },
    act: async (page) => {
      await page.getByLabel("Email").fill("analyst@example.org");
      await page.getByRole("button", { name: "Continue" }).click();
      await page.getByText("a link is on its way").waitFor();
    },
  },
  {
    name: "02d-signin-sso-choice",
    url: "/",
    options: {
      mode: "oidc",
      signedIn: false,
      discover: { methods: ["sso", "sign_in_link"], sso_kind: "entra" },
    },
    act: async (page) => {
      await page.getByLabel("Email").fill("analyst@example.org");
      await page.getByRole("button", { name: "Continue" }).click();
      await page.getByRole("button", { name: "Email me a sign-in link instead" }).waitFor();
    },
  },
  {
    name: "03-finish-sign-in",
    url: "/auth/finish#token=synthetic-token-abcdefghijklmnop",
    options: { mode: "oidc", signedIn: false },
  },
  {
    name: "04-app-loading",
    url: "/",
    options: { overrides: [{ path: "^/auth/mode$", hang: true }] },
  },
  { name: "05-consent-first", url: "/", options: { consentPending: true } },
  {
    name: "05b-consent-changed",
    url: "/",
    options: { consentPending: true, consentChanged: true },
  },
  {
    name: "05c-consent-error",
    url: "/",
    options: { consentPending: true, overrides: [{ path: "^/consent$", status: 500 }] },
  },
  { name: "06-conversations", url: "/" },
  { name: "06b-conversations-admin-operator", url: "/", options: ADMIN },
  { name: "06c-conversations-empty", url: "/", options: { conversations: [] } },
  {
    name: "06d-conversations-loading",
    url: "/",
    options: { overrides: [{ path: "^/conversations$", hang: true }] },
  },
  {
    name: "06e-conversations-error",
    url: "/",
    options: { overrides: [{ path: "^/conversations$", status: 500 }] },
  },
  { name: "07-start-panel-single", url: "/new" },
  { name: "07b-start-panel-choices", url: "/new", options: CHOICES },
  {
    name: "07c-start-panel-external",
    url: "/new",
    options: CHOICES,
    act: async (page) => {
      await page.getByLabel("Model").selectOption("external-large");
    },
  },
  {
    name: "07d-start-panel-no-reasoning",
    url: "/new",
    options: { models: [F.MODEL_FAST, F.MODEL_EU] },
  },
  {
    name: "07e-start-panel-loading",
    url: "/new",
    options: { overrides: [{ path: "^/models$", hang: true }] },
  },
  {
    name: "07f-start-panel-error",
    url: "/new",
    options: { overrides: [{ path: "^/models$", status: 500 }] },
  },
  { name: "07g-start-panel-no-workspace", url: "/new", options: { workspaces: [] } },
  {
    name: "07h-start-panel-refused",
    url: "/new",
    options: {
      overrides: [
        {
          path: "^/conversations$",
          method: "POST",
          status: 422,
          json: { detail: "model_not_enabled" },
        },
      ],
    },
    act: async (page) => {
      await askFirstQuestion(page);
      await page.getByRole("alert").waitFor();
    },
  },
  {
    name: "08-chat-searching",
    url: "/new",
    options: { overrides: [{ path: "/messages$", hang: true }] },
    act: async (page) => {
      await askFirstQuestion(page);
      await page.getByText("Searching your research package").waitFor();
    },
  },
  { name: "08b-chat-answer", url: "/new", act: answered },
  {
    name: "08c-chat-answer-citation-open",
    url: "/new",
    act: async (page) => {
      await answered(page);
      await page.getByRole("button", { name: "Citation 1" }).click();
      await page.getByRole("complementary", { name: "Citations" }).waitFor();
    },
  },
  {
    name: "08d-chat-error",
    url: "/new",
    options: { answerError: "retrieval_unavailable" },
    act: async (page) => {
      await askFirstQuestion(page);
      await page.getByText("research library is unavailable").waitFor();
    },
  },
  {
    name: "08e-chat-spend-cap-notice",
    url: "/new",
    options: { models: [F.MODEL_EXT, F.MODEL_EU], spendCapNotice: true },
    act: answered,
  },
  {
    name: "08f-chat-no-history",
    url: "/new",
    options: { noHistory: true },
    act: async (page) => {
      await askFirstQuestion(page);
      await page.getByTestId("no-history").waitFor();
      await page.getByText("Synthetic capacity grew by 12%").waitFor();
    },
  },
  {
    name: "09-chat-long-answer-many-citations",
    url: `/c/${LONG_CONVERSATION}`,
    act: async (page) => {
      await page.getByRole("button", { name: "Citation 9" }).first().click();
      await page.getByRole("complementary", { name: "Citations" }).waitFor();
    },
  },
  {
    name: "09b-chat-long-answer-closed",
    url: `/c/${LONG_CONVERSATION}`,
    act: async (page) => {
      await page.getByRole("button", { name: "Citation 2" }).first().waitFor();
    },
  },
  {
    name: "09c-chat-notes-abstain-unsupported",
    url: `/c/${NOTES_CONVERSATION}`,
    act: async (page) => {
      await page.getByTestId("nothing-found").waitFor();
    },
  },
  {
    name: "09d-chat-not-found",
    url: `/c/${C(99)}`,
    act: async (page) => {
      await page.getByText("Conversation not found").waitFor();
    },
  },
  { name: "10-files", url: FILES },
  { name: "10b-files-empty", url: FILES, options: { files: [] } },
  {
    name: "10c-files-loading",
    url: FILES,
    options: { overrides: [{ path: "/files$", hang: true }] },
  },
  {
    name: "10d-files-error",
    url: FILES,
    options: { overrides: [{ path: "/files$", status: 500 }] },
  },
  {
    name: "11-tenant-admin",
    url: "/admin",
    options: { ...CHOICES, role: "tenant_admin" },
    act: async (page) => {
      await page.getByText("Version history").first().waitFor();
    },
  },
  {
    name: "11b-tenant-admin-history-open",
    url: "/admin",
    options: { role: "tenant_admin" },
    act: async (page) => {
      await page.getByText("Version history").first().click();
    },
  },
  {
    name: "11c-tenant-admin-remove-confirm",
    url: "/admin",
    options: { role: "tenant_admin" },
    act: async (page) => {
      await page.getByRole("button", { name: "Actions for invited@example.org" }).click();
      await page.getByRole("menuitem", { name: "Remove" }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  { name: "11d-tenant-admin-not-admin", url: "/admin" },
  { name: "12-operator-console", url: "/operator", options: ADMIN },
  { name: "12b-operator-only", url: "/operator" },
  { name: "13-operator-tenant-entitlements", url: TENANT, options: ADMIN },
  { name: "13b-operator-tenant-login", url: `${TENANT}?tab=login`, options: ADMIN },
  { name: "13c-operator-tenant-workspaces", url: `${TENANT}?tab=workspaces`, options: ADMIN },
  { name: "13d-operator-tenant-users", url: `${TENANT}?tab=users`, options: ADMIN },
  { name: "13e-operator-tenant-spend", url: `${TENANT}?tab=spend`, options: ADMIN },
  { name: "14-operator-aggregates", url: "/operator/aggregates", options: ADMIN },
  { name: "15-content-register", url: "/content", options: CONTENT },
  {
    name: "15b-content-register-empty",
    url: "/content",
    options: { ...CONTENT, contentSources: [] },
  },
  { name: "15c-content-roles-only", url: "/content", options: { contentRoles: null } },
  {
    name: "16-content-source-detail",
    url: `/content/sources/${F.SOURCE_DETAIL.id}`,
    options: CONTENT,
  },
  { name: "17-content-propose", url: "/content/propose", options: CONTENT },
  { name: "18-content-takedowns", url: "/content/takedowns", options: CONTENT },
  { name: "19-content-sites", url: "/content/sites", options: CONTENT },
  { name: "19b-content-site-detail", url: `/content/sites/${F.SITE_ID}`, options: CONTENT },
  { name: "20-content-tags", url: "/content/tags", options: CONTENT },
  // UX-06: the development-only component gallery.
  { name: "21-ui-gallery", url: "/_ui" },
];
