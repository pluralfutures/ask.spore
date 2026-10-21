// Typed client for /api/v1. The browser never talks to RAGFlow or the LLM.
import { readEvents } from "../lib/sse";
import type {
  AdminInviteIn,
  AdminUser,
  AuthMode,
  ChatStreamEvent,
  ConversationCreated,
  ConversationCreateIn,
  ConversationDetail,
  ConversationSummary,
  DiscoverOut,
  DownloadLink,
  FeedbackIn,
  FeedbackOut,
  EntitlementsIn,
  EntitlementsOut,
  LoginPolicyIn,
  LoginPolicyOut,
  SsoSourceIn,
  SsoStartOut,
  Me,
  ModelOption,
  NoticeOut,
  OperatorOptions,
  OperatorSource,
  OperatorWorkspace,
  TenantCreateIn,
  TenantOut,
  TenantSettings,
  UserChangeIn,
  UserInviteIn,
  Workspace,
  WorkspaceCreateIn,
  WorkspaceDefaultsIn,
  WorkspaceFiles,
  WorkspacePrompt,
} from "./types";

const BASE = "/api/v1";

// Two sign-in modes, chosen by the API ([auth] mode, GET /auth/mode):
// - "oidc" (P1a-02): emailed sign-in links. The session is an HttpOnly cookie set by the
//   API; this code never sees a token.
// - "phase0" (P0-06, kept for the eval harness): the shared bearer token and the user's
//   email, entered once per browser session and kept in sessionStorage, never in the
//   bundle.
export interface Credentials {
  token: string;
  email: string;
}

const CREDENTIALS_KEY = "askspore.phase0.credentials";

export function loadCredentials(): Credentials | null {
  try {
    const raw = sessionStorage.getItem(CREDENTIALS_KEY);
    return raw ? (JSON.parse(raw) as Credentials) : null;
  } catch {
    return null;
  }
}

export function saveCredentials(credentials: Credentials): void {
  try {
    sessionStorage.setItem(CREDENTIALS_KEY, JSON.stringify(credentials));
  } catch {
    // Storage unavailable: the user signs in again on reload.
  }
}

export function clearCredentials(): void {
  try {
    sessionStorage.removeItem(CREDENTIALS_KEY);
  } catch {
    // ignore
  }
}

export class ApiError extends Error {
  // `code`: the API's `detail` when it is a short code such as "workspace_required".
  constructor(
    readonly status: number,
    readonly code: string | null = null,
  ) {
    super(`API request failed with status ${status}`);
  }
}

async function errorCode(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return null;
  }
}

let onUnauthorized: () => void = () => {};

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

async function send(method: string, path: string, body?: unknown, signal?: AbortSignal) {
  const credentials = loadCredentials();
  const headers: Record<string, string> = {};
  if (credentials) {
    headers.Authorization = `Bearer ${credentials.token}`;
    headers["X-User-Email"] = credentials.email;
  }
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
    credentials: "same-origin",
  });
  if (response.status === 401) {
    clearCredentials();
    onUnauthorized();
  }
  if (!response.ok) throw new ApiError(response.status, await errorCode(response));
  return response;
}

async function json<T>(method: string, path: string, body?: unknown): Promise<T> {
  return (await (await send(method, path, body)).json()) as T;
}

export async function authMode(): Promise<AuthMode> {
  const response = await fetch(`${BASE}/auth/mode`, { credentials: "same-origin" });
  if (!response.ok) return "phase0";
  return ((await response.json()) as { mode: AuthMode }).mode;
}

// The emailed link's landing page (P1a-02) calls this, and only from its button.
// "no_binding" (P1b-08): this browser did not ask for the link, so it cannot finish it.
export type SignInResult = "ok" | "no_binding" | "failed";

export async function completeSignIn(
  token: string,
  fetchImpl: typeof fetch = fetch,
): Promise<SignInResult> {
  const response = await fetchImpl(`${BASE}/auth/link/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
    credentials: "same-origin",
  });
  if (response.ok) return "ok";
  return (await errorCode(response)) === "no_binding" ? "no_binding" : "failed";
}

// Tenant discovery (P1b-06): the methods the address's domain allows. Any unknown domain
// gets the links-only answer, like every domain without SSO.
export async function discoverMethods(email: string): Promise<DiscoverOut> {
  const response = await fetch(`${BASE}/auth/discover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as DiscoverOut;
}

// SSO (P1b-07): where to send the browser to sign in at the organisation's IdP, or null
// when the address's domain has no SSO.
export async function startSso(email: string): Promise<string | null> {
  const response = await fetch(`${BASE}/auth/sso/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
    credentials: "same-origin",
  });
  if (response.status === 409) return null;
  if (!response.ok) throw new ApiError(response.status);
  return ((await response.json()) as SsoStartOut).redirect_url;
}

export async function requestSignInLink(email: string): Promise<void> {
  const response = await fetch(`${BASE}/auth/link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status);
}

export async function signOut(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, { method: "POST", credentials: "same-origin" });
}

export async function currentUser(): Promise<Me | null> {
  const response = await fetch(`${BASE}/me`, { credentials: "same-origin" });
  if (response.status === 401) return null;
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as Me;
}

export const api = {
  me: () => json<Me>("GET", "/me"),
  listConversations: () => json<ConversationSummary[]>("GET", "/conversations"),
  workspaces: () => json<Workspace[]>("GET", "/workspaces"),
  models: () => json<ModelOption[]>("GET", "/models"),
  createConversation: (body: ConversationCreateIn) =>
    json<ConversationCreated>("POST", "/conversations", body),
  getConversation: (id: string) => json<ConversationDetail>("GET", `/conversations/${id}`),
  deleteConversation: async (id: string) => {
    await send("DELETE", `/conversations/${id}`);
  },
  // Workspace file list and downloads (P1a-14).
  workspaceFiles: (workspaceId: string) =>
    json<WorkspaceFiles>("GET", `/workspaces/${workspaceId}/files`),
  async download(workspaceId: string, sourceId: string): Promise<{ blob: Blob; name: string }> {
    const link = await json<DownloadLink>(
      "POST",
      `/workspaces/${workspaceId}/files/${sourceId}/download`,
    );
    // The single-use link, fetched at once with the same credentials.
    const response = await send("GET", link.url.replace(/^\/api\/v1/, ""));
    const disposition = response.headers.get("content-disposition") ?? "";
    const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "download";
    return { blob: await response.blob(), name };
  },
  sendFeedback: (messageId: string, feedback: FeedbackIn) =>
    json<FeedbackOut>("POST", `/messages/${messageId}/feedback`, feedback),
  async *ask(id: string, question: string, signal?: AbortSignal): AsyncGenerator<ChatStreamEvent> {
    const response = await send("POST", `/conversations/${id}/messages`, { question }, signal);
    yield* readEvents(response);
  },
};

// Tenant admin pages (P1a-13). The API answers 403 to anyone who is not a tenant admin.
export const adminApi = {
  users: () => json<AdminUser[]>("GET", "/admin/users"),
  invite: (body: UserInviteIn) => json<AdminUser>("POST", "/admin/users", body),
  changeUser: (userId: string, body: UserChangeIn) =>
    json<AdminUser>("PATCH", `/admin/users/${userId}`, body),
  setDefaults: (workspaceId: string, body: WorkspaceDefaultsIn) =>
    json<Workspace>("PUT", `/admin/workspaces/${workspaceId}/defaults`, body),
  prompts: (workspaceId: string) =>
    json<WorkspacePrompt[]>("GET", `/workspaces/${workspaceId}/prompts`),
  savePrompt: (workspaceId: string, text: string) =>
    json<WorkspacePrompt>("PUT", `/workspaces/${workspaceId}/prompt`, { text }),
  settings: () => json<TenantSettings>("GET", "/admin/settings"),
  // P1b-07: how the tenant's users sign in, read-only (the operator configures it).
  loginPolicy: () => json<LoginPolicyOut>("GET", "/admin/login-policy"),
  setRetention: (days: number) =>
    json<TenantSettings>("PUT", "/admin/settings/retention", { retention_days: days }),
};

// Operator console (P1a-03). The API answers 403 to anyone who is not an operator.
export const operatorApi = {
  options: () => json<OperatorOptions>("GET", "/operator/options"),
  tenants: () => json<TenantOut[]>("GET", "/operator/tenants"),
  createTenant: (body: TenantCreateIn) => json<TenantOut>("POST", "/operator/tenants", body),
  inviteAdmin: (tenantId: string, body: AdminInviteIn) =>
    json<{ user_id: string; status: "invited" }>(
      "POST",
      `/operator/tenants/${tenantId}/admins`,
      body,
    ),
  setEntitlements: (tenantId: string, body: EntitlementsIn) =>
    json<EntitlementsOut>("PUT", `/operator/tenants/${tenantId}/entitlements`, body),
  // Login policy (P1b-06): sign-in links, JIT provisioning, MFA for tenant admins.
  setLoginPolicy: (tenantId: string, body: LoginPolicyIn) =>
    json<LoginPolicyOut>("PUT", `/operator/tenants/${tenantId}/login-policy`, body),
  // P1b-07: the tenant's SSO source, configured in Authentik; secrets are write-only.
  setSsoSource: (tenantId: string, body: SsoSourceIn) =>
    json<LoginPolicyOut>("PUT", `/operator/tenants/${tenantId}/login-policy/sso`, body),
  removeSsoSource: (tenantId: string) =>
    json<LoginPolicyOut>("DELETE", `/operator/tenants/${tenantId}/login-policy/sso`),
  notices: () => json<NoticeOut[]>("GET", "/operator/notices"),
  // Package builder (P1a-04): a tenant's workspaces and their tags.
  workspaces: (tenantId: string) =>
    json<OperatorWorkspace[]>("GET", `/operator/tenants/${tenantId}/workspaces`),
  createWorkspace: (tenantId: string, body: WorkspaceCreateIn) =>
    json<OperatorWorkspace>("POST", `/operator/tenants/${tenantId}/workspaces`, body),
  // The download switch per source (P1a-14).
  sources: () => json<OperatorSource[]>("GET", "/operator/sources"),
  setDownloadable: (sourceId: string, downloadable: boolean) =>
    json<OperatorSource>("PUT", `/operator/sources/${sourceId}/downloadable`, { downloadable }),
  setWorkspaceTags: (tenantId: string, workspaceId: string, tagIds: string[]) =>
    json<OperatorWorkspace>("PUT", `/operator/tenants/${tenantId}/workspaces/${workspaceId}/tags`, {
      tag_ids: tagIds,
    }),
};
