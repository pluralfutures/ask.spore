// Typed client for /api/v1. The browser never talks to RAGFlow or the LLM.
import { auditLogQuery } from "../lib/admin";
import { readEvents } from "../lib/sse";
import type {
  AdminInviteIn,
  AdminUser,
  Aggregates,
  ApproveIn,
  AuthMode,
  ChatStreamEvent,
  ConsentNotice,
  ContentMe,
  ContentSite,
  ContentSiteDetail,
  ContentSource,
  ContentSourceDetail,
  ContentTag,
  ConversationCreateIn,
  ConversationCreated,
  ConversationDetail,
  ConversationSummary,
  DiscoverOut,
  DownloadLink,
  EntitlementsIn,
  EntitlementsOut,
  FeedbackIn,
  FeedbackOut,
  InvitationResent,
  LoginPolicyIn,
  LoginPolicyOut,
  Me,
  MfaRequiredOut,
  ModelOption,
  NoticeOut,
  OperatorOptions,
  OperatorSource,
  OperatorTag,
  OperatorWorkspace,
  ProposeOut,
  SiteCreateIn,
  SiteSettingsIn,
  SsoSourceIn,
  SsoStartOut,
  TagSync,
  Takedown,
  TakedownIn,
  TenantCreateIn,
  TenantOut,
  TenantSettings,
  OperatorSupportGrant,
  SupportConversation,
  SupportGrant,
  SupportGrantIn,
  SupportSettings,
  UsageOut,
  TenantSpend,
  TerminatedTenant,
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

// P1b-10: a route refused for want of consent (the notice version changed during the
// session) sends the app back to the consent gate.
export const CONSENT_REQUIRED = "consent_required";
let onConsentRequired: () => void = () => {};

export function setConsentRequiredHandler(handler: () => void): void {
  onConsentRequired = handler;
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
  if (!response.ok) {
    const code = await errorCode(response);
    if (response.status === 403 && code === CONSENT_REQUIRED) onConsentRequired();
    throw new ApiError(response.status, code);
  }
  return response;
}

async function json<T>(method: string, path: string, body?: unknown): Promise<T> {
  return (await (await send(method, path, body)).json()) as T;
}

// A multipart form (uploads in the content console, P1b-05); the browser sets the
// boundary, so no Content-Type here.
async function sendForm(method: string, path: string, form: FormData): Promise<Response> {
  const response = await fetch(`${BASE}${path}`, {
    method,
    body: form,
    credentials: "same-origin",
  });
  if (response.status === 401) onUnauthorized();
  if (!response.ok) throw new ApiError(response.status, await errorCode(response));
  return response;
}

export async function authMode(): Promise<AuthMode> {
  const response = await fetch(`${BASE}/auth/mode`, { credentials: "same-origin" });
  if (!response.ok) return "phase0";
  return ((await response.json()) as { mode: AuthMode }).mode;
}

// The emailed link's landing page (P1a-02) calls this, and only from its button.
// "no_binding" (P1b-08): this browser did not ask for the link, so it cannot finish it.
// A tenant admin's link may first ask for a second factor (P1b-08): the challenge.
export type SignInResult = "ok" | "no_binding" | "failed" | MfaRequiredOut;

async function signInResult(response: Response): Promise<SignInResult> {
  if (response.status === 200) return (await response.json()) as MfaRequiredOut;
  if (response.ok) return "ok";
  return (await errorCode(response)) === "no_binding" ? "no_binding" : "failed";
}

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
  return signInResult(response);
}

// The admin's code for the pending second factor, from the same browser (P1b-08).
export async function answerMfa(
  code: string,
  fetchImpl: typeof fetch = fetch,
): Promise<SignInResult> {
  const response = await fetchImpl(`${BASE}/auth/mfa`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
    credentials: "same-origin",
  });
  return signInResult(response);
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

// P1b-08: renew the session from the refresh cookie before the access token expires.
export async function refreshSession(): Promise<boolean> {
  const response = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    credentials: "same-origin",
  });
  return response.ok;
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
  // P1b-10: the active use and privacy notice, and accepting the version shown.
  consent: () => json<ConsentNotice>("GET", "/consent"),
  acceptConsent: (version: string) => json<ConsentNotice>("POST", "/consent", { version }),
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

export type AuditExport = { blob: Blob; name: string; complete: boolean; next: string | null };

// Tenant admin pages (P1a-13). The API answers 403 to anyone who is not a tenant admin.
export const adminApi = {
  users: () => json<AdminUser[]>("GET", "/admin/users"),
  invite: (body: UserInviteIn) => json<AdminUser>("POST", "/admin/users", body),
  changeUser: (userId: string, body: UserChangeIn) =>
    json<AdminUser>("PATCH", `/admin/users/${userId}`, body),
  // P1c-07: the invitation email again for a user still invited; remove a user.
  resendInvitation: (userId: string) =>
    json<InvitationResent>("POST", `/admin/users/${userId}/invitation`),
  removeUser: async (userId: string): Promise<void> => {
    await send("DELETE", `/admin/users/${userId}`);
  },
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
  // P1b-10, P2A-07: the tenant's exported audit events between two dates, as CSV. A
  // period over the row cap comes in parts: `next` is the cursor of the next one.
  auditLog: async (since: string, until: string, after?: string | null): Promise<AuditExport> => {
    const response = await send("GET", `/admin/audit-log${auditLogQuery(since, until, after)}`);
    const disposition = response.headers.get("content-disposition") ?? "";
    return {
      blob: await response.blob(),
      name: /filename="([^"]+)"/.exec(disposition)?.[1] ?? "audit-log.csv",
      complete: response.headers.get("x-audit-export-complete") !== "false",
      next: response.headers.get("x-audit-export-next"),
    };
  },
  // P2A-05: questions, active users, cited sources and (with external models) cost.
  usage: () => json<UsageOut>("GET", "/admin/usage"),
  // P2A-08: grant the operators a time-boxed read, list the grants, revoke one.
  supportGrants: () => json<SupportGrant[]>("GET", "/admin/support-grants"),
  grantSupport: (body: SupportGrantIn) => json<SupportGrant>("POST", "/admin/support-grants", body),
  revokeSupport: (grantId: string) =>
    json<SupportGrant>("POST", `/admin/support-grants/${grantId}/revoke`),
};

// Operator console (P1a-03). The API answers 403 to anyone who is not an operator.
export const operatorApi = {
  options: () => json<OperatorOptions>("GET", "/operator/options"),
  tenants: () => json<TenantOut[]>("GET", "/operator/tenants"),
  // P1c-08: tenants the termination purge emptied, with purge date and certificate.
  terminatedTenants: () => json<TerminatedTenant[]>("GET", "/operator/terminated-tenants"),
  // P1b-12: one tenant per page, its users and spend, and the cross-tenant totals.
  tenant: (tenantId: string) => json<TenantOut>("GET", `/operator/tenants/${tenantId}`),
  tenantTags: (tenantId: string) =>
    json<OperatorTag[]>("GET", `/operator/tenants/${tenantId}/tags`),
  tenantUsers: (tenantId: string) =>
    json<AdminUser[]>("GET", `/operator/tenants/${tenantId}/users`),
  tenantSpend: (tenantId: string) =>
    json<TenantSpend>("GET", `/operator/tenants/${tenantId}/spend`),
  aggregates: () => json<Aggregates>("GET", "/operator/aggregates"),
  // P2A-08: the tenant's open support grants, and the reads they allow (404 otherwise).
  supportGrants: (tenantId: string) =>
    json<OperatorSupportGrant[]>("GET", `/operator/tenants/${tenantId}/support-grants`),
  supportSettings: (tenantId: string, grantId: string) =>
    json<SupportSettings>(
      "GET",
      `/operator/tenants/${tenantId}/support-grants/${grantId}/settings`,
    ),
  supportConversation: (tenantId: string, grantId: string, conversationId: string) =>
    json<SupportConversation>(
      "GET",
      `/operator/tenants/${tenantId}/support-grants/${grantId}/conversations/${conversationId}`,
    ),
  createTenant: (body: TenantCreateIn) => json<TenantOut>("POST", "/operator/tenants", body),
  inviteAdmin: (tenantId: string, body: AdminInviteIn) =>
    json<{ user_id: string; status: "invited" }>(
      "POST",
      `/operator/tenants/${tenantId}/admins`,
      body,
    ),
  // P1c-07: the invitation email again, and removing a tenant's user.
  resendInvitation: (tenantId: string, userId: string) =>
    json<InvitationResent>("POST", `/operator/tenants/${tenantId}/users/${userId}/invitation`),
  removeUser: async (tenantId: string, userId: string): Promise<void> => {
    await send("DELETE", `/operator/tenants/${tenantId}/users/${userId}`);
  },
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

// Content console (P1b-05). The API answers 403 to anyone without a content role, and
// to an editor on a reviewer's action. Register metadata only, never document text.
export interface SourceFilters {
  status?: string;
  tag?: string;
  type?: string;
  publisher?: string;
  site_id?: string;
}

function query(params: object): string {
  const entries = Object.entries(params).filter(
    (entry): entry is [string, string] => typeof entry[1] === "string" && entry[1] !== "",
  );
  return entries.length ? `?${new URLSearchParams(entries).toString()}` : "";
}

export const contentApi = {
  me: () => json<ContentMe>("GET", "/content/me"),
  sources: (filters: SourceFilters = {}) =>
    json<ContentSource[]>("GET", `/content/sources${query(filters)}`),
  source: (id: string) => json<ContentSourceDetail>("GET", `/content/sources/${id}`),
  licenceUrl: (id: string) => `${BASE}/content/sources/${id}/licence`,
  propose: async (form: FormData) =>
    (await (await sendForm("POST", "/content/sources", form)).json()) as ProposeOut,
  attachLicence: async (id: string, form: FormData) => {
    await sendForm("PUT", `/content/sources/${id}/licence`, form);
  },
  approve: (id: string, body: ApproveIn) =>
    json<{ job_id: string }>("POST", `/content/sources/${id}/approve`, body),
  reject: async (id: string, note: string) => {
    await send("POST", `/content/sources/${id}/reject`, { note });
  },
  retry: (id: string) => json<{ job_id: string }>("POST", `/content/sources/${id}/retry`),
  withdraw: (id: string, reason: string) =>
    json<{ job_id: string }>("POST", `/content/sources/${id}/withdraw`, { reason }),
  // P1c-14: a withdrawn crawled page comes back at the next crawl of its site.
  restore: async (id: string) => {
    await send("POST", `/content/sources/${id}/restore`);
  },
  takedown: (id: string, body: TakedownIn) =>
    json<Takedown>("POST", `/content/sources/${id}/takedown`, body),
  takedowns: () => json<Takedown[]>("GET", "/content/takedowns"),
  sites: () => json<ContentSite[]>("GET", "/content/sites"),
  site: (id: string) => json<ContentSiteDetail>("GET", `/content/sites/${id}`),
  createSite: (body: SiteCreateIn) => json<ContentSite>("POST", "/content/sites", body),
  approveSite: (id: string, note: string | null) =>
    json<{ job_id: string }>("POST", `/content/sites/${id}/approve`, { note }),
  rejectSite: async (id: string, note: string) => {
    await send("POST", `/content/sites/${id}/reject`, { note });
  },
  siteSettings: async (id: string, body: SiteSettingsIn) => {
    await send("PUT", `/content/sites/${id}/settings`, body);
  },
  siteWhitelist: async (id: string, patterns: string[]) => {
    await send("PUT", `/content/sites/${id}/special-category-allow`, { patterns });
  },
  crawl: (id: string) => json<{ job_id: string }>("POST", `/content/sites/${id}/crawl`),
  // P1c-14: retires the site and withdraws every page, one job per page.
  withdrawSite: (id: string, reason: string) =>
    json<{ job_ids: string[] }>("POST", `/content/sites/${id}/withdraw`, { reason }),
  tags: () => json<ContentTag[]>("GET", "/content/tags"),
  syncTags: () => json<TagSync[]>("POST", "/content/tags/sync"),
};
